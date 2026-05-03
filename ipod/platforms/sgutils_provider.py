import errno
import subprocess
from dataclasses import dataclass
from math import ceil
from typing import Iterator

import pyudev

from .base import BaseSCSIDevice
from .pyusb_provider import PyUSBProvider
from ..scsi import CommandDataBuffer, DataTransferDirection


@dataclass
class UDevSCSIGenericDevice:
	sys_name: str  # like "sg0"
	vendor_id: int
	product_id: int
	serial: str
	bus_number: int
	device_number: int


class SG3Error(RuntimeError):
	...


class SG3PermissionError(SG3Error, PermissionError):
	...


class _SGUtilsSCSIDevice(BaseSCSIDevice):
	def __init__(self, device_path: str):
		# device_path is like /dev/sg0
		self._device_path = device_path

	def raw_command(self, cdb: CommandDataBuffer) -> bytes | None:
		raw_cdb = cdb.to_bytes()
		process = subprocess.Popen([
			"sg_raw",
			"--binary",
			"--raw",
			f"--request={ceil(cdb.incoming_data_length / 0x100) * 0x100}",  # wiggle room!
			f"--send={len(cdb.outgoing_data) if cdb.outgoing_data else 0}",
			self._device_path,
			*(raw_cdb.hex(" ").split(" "))
		],
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE
		)
		if cdb.outgoing_data:
			process.stdin.write(cdb.outgoing_data)
		process.wait()
		if process.returncode != 0:
			# see "Exit status" in https://sg.danny.cz/sg/sg3_utils.html
			error_class = SG3Error
			if 51 <= process.returncode <= 96:
				errno_code = process.returncode - 50
				if errno_code == errno.EACCES:
					error_class = SG3PermissionError

			raise error_class(process.stderr.read().decode("ascii"))

		if cdb.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			return process.stdout.read()

		return None


def _udev_list_scsi_generic_devices() -> Iterator[UDevSCSIGenericDevice]:
	context = pyudev.Context()

	for device in context.list_devices().match_subsystem("scsi_generic"):
		sys_name = device.sys_name

		for ancestor in device.ancestors:
			if ancestor.subsystem != "usb":
				continue

			attributes = {
				key: ancestor.attributes.get(key)
				for key in ancestor.attributes.available_attributes
			}
			if "serial" not in attributes:
				continue

			yield UDevSCSIGenericDevice(
				sys_name=sys_name,
				serial=attributes["serial"].decode("ascii"),
				vendor_id=int(attributes["idVendor"].decode("ascii"), 16),
				product_id=int(attributes["idProduct"].decode("ascii"), 16),
				bus_number=int(attributes["busnum"].decode("ascii"), 10),
				device_number=int(attributes["devnum"].decode("ascii"), 10)
			)
			break


class SGUtilsUSBProvider(PyUSBProvider):
	# inherits everything from PyUSBProvider except custom SCSI logic.

	def get_scsi_device(self, device_id: str):
		connected_device = self.get_connected_device(device_id)
		for generic_device in _udev_list_scsi_generic_devices():
			if (
					generic_device.bus_number == connected_device.bus and
					generic_device.device_number == connected_device.address
			):
				return _SGUtilsSCSIDevice(f"/dev/{generic_device.sys_name}")

		raise ValueError("no SCSI device found")
