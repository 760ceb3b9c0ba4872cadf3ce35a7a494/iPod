"""
implementation of the Device Firmware Update (DFU) protocol
"""

from __future__ import annotations

import io
import math
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Callable, Optional

import usb.core

from .definitions import iPodMode, USB_PID_INDEX, iPodTarget
from .dfu import DFUDevice, DFUDeviceState
from .scsi import CommandDataBuffer, iPodSubcommand, DataTransferDirection
from .usb_mass_storage import HostDevice
from .utils import buffered


def find_raw_devices() -> list[tuple[iPodTarget, usb.core.Device]]:
	return [
		(USB_PID_INDEX[device.idProduct], device)
		for device in usb.core.find(find_all=True, idVendor=0x05ac)
		if device.idProduct in USB_PID_INDEX
	]


def device_from_raw_device(raw_device: tuple[iPodTarget, usb.core.Device]) -> iPodDeviceDiskMode | iPodDeviceWTF | iPodDeviceDFU:
	(target, device) = raw_device

	return (
		iPodDeviceDiskMode(
			target=target,
			device=device
		) if target.mode == iPodMode.DISK else

		iPodDeviceWTF(
			target=target,
			device=device
		) if target.mode == iPodMode.WTF else

		iPodDeviceDFU(
			target=target,
			device=device
		) if target.mode == iPodMode.DFU else
		None
	)


def find_devices():
	return [
		device_from_raw_device(raw_device) for raw_device in find_raw_devices()
	]


@dataclass(kw_only=True)
class iPodDevice:
	target: iPodTarget
	device: usb.core.Device


class iPodUpdateKind(Enum):
	BOOTLOADER = "bootloader"
	FIRMWARE = "firmware"


class iPodDeviceDiskMode(iPodDevice):
	def __init__(
			self,
			*,
			target: iPodTarget,
			device: usb.core.Device
	):
		super().__init__(
			target=target,
			device=device
		)

		self._kernel_driver_detached = False
		self.ms_host = self._initialize_host()
		print(f"Created: {id(self)}")

	def get_device_information_raw(self):
		x = self.ms_host.inquiry_vital_product_data(0xc0, 0xfc)
		stream = io.BytesIO()
		for page in range(0xc2, 0xff):
			data = self.ms_host.inquiry_vital_product_data(page, 0xfc)
			stream.write(data)
			if len(data) < 0xfc - 4:
				break
		stream.seek(0)
		return stream.read()

	def test(self):
		self.ms_host.inquiry_vital_product_data(0x0, 0x10)

	def get_device_information(self):
		data = self.get_device_information_raw()
		decoded_data = plistlib.loads(data)
		return decoded_data

	def reboot(self):
		self.device.reset()
		usb.util.dispose_resources(self.device)
		# self.ms_host.raw_command(CommandDataBuffer(
		# 	operation_code=0x1b,  # "START STOP UNIT"
		# 	request=bytes([0, 0, 0, 0b00000010])  # i think the "LOEJ" bit was set
		# ))

	def get_capacity(self) -> tuple[int, int]:
		# returns: block count, block size
		data = self.ms_host.raw_command(CommandDataBuffer(
			operation_code=0x25,
			request=bytes(8),
			incoming_data_length=8,
			data_transfer_direction=DataTransferDirection.FROM_DEVICE
		))

		block_count = int.from_bytes(data[:4], "big")
		block_size = int.from_bytes(data[4:8], "big")
		return block_count, block_size

	def _update_start(self, kind: iPodUpdateKind, length: int):
		stream = io.BytesIO()
		stream.write(bytes([iPodSubcommand.UPDATE_START]))
		stream.write(bytes([
			1 if kind == iPodUpdateKind.BOOTLOADER else
			0 if kind == iPodUpdateKind.FIRMWARE else
			0
		]))
		stream.write(int.to_bytes(length, 4, "big"))
		stream.seek(0)
		self.ms_host.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=stream.read(),
		))

	def _update_end(self):
		self.ms_host.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=bytes([iPodSubcommand.UPDATE_END])
		))

	def repartition(self, size):
		if size % 0x1000:
			raise Exception("invalid size, must be divisible by 4096")
		stream = io.BytesIO()
		stream.write(bytes([iPodSubcommand.REPARTITION]))
		stream.write(int.to_bytes(size, 4, "big"))
		stream.seek(0)
		self.ms_host.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=stream.read(),
		))

	def _update_send_block(self, stream: BinaryIO, length: int):
		content = stream.read(length)

		if len(content) % 0x1000 != 0:
			content += bytes(0x1000 - (len(content) % 0x1000))

		if len(content) % 0x1000 != 0:
			raise Exception("block has invalid size, must be divisible by 4096")

		sector_count = len(content) // 0x1000
		request_stream = io.BytesIO()
		request_stream.write(bytes([iPodSubcommand.UPDATE_CHUNK]))
		request_stream.write(int.to_bytes(sector_count, 2, "big"))  # "nsectors"
		request_stream.seek(0)

		self.ms_host.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=request_stream.read(),
			outgoing_data=content,
			data_transfer_direction=DataTransferDirection.TO_DEVICE
		))

	def finalize_updates(self):
		self.ms_host.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=bytes([iPodSubcommand.UPDATE_FINALIZE])  # i think the "LOEJ" bit was set
		))

	def update(
			self,
			kind: iPodUpdateKind,
			stream: BinaryIO,
			length: int,
			on_progress: Optional[Callable[[iPodFirmwareSendState], None]] = None
	):
		self._update_start(kind, length)
		block_size = 0x1000 * 8
		block_count = math.ceil(length / block_size)
		for block_number in range(block_count):
			self._update_send_block(stream, block_size)
			if on_progress:
				on_progress(iPodFirmwareSendState(
					block_number=block_number,
					block_count=block_count
				))

		if on_progress:
			on_progress(iPodFirmwareSendState(
				block_number=block_count,
				block_count=block_count
			))

		self._update_end()  # this can take some time

	def _initialize_host(self):
		configuration: usb.core.Configuration = self.device.get_active_configuration()

		# Find the mass storage interface
		self.mass_storage_interface: usb.core.Interface | None = None
		for interface in configuration.interfaces():
			if interface.bInterfaceClass == 0x08:
				# https://www.usb.org/defined-class-codes#anchor_BaseClass08h 8 = mass storage
				self.mass_storage_interface = interface
				break

		if not self.mass_storage_interface:
			raise Exception("cant find mass storage interface...")

		# find the endpoints
		in_endpoint: usb.core.Endpoint | None = None
		out_endpoint: usb.core.Endpoint | None = None
		for endpoint in self.mass_storage_interface.endpoints():
			endpoint_direction = usb.util.endpoint_direction(endpoint.bEndpointAddress)
			if endpoint_direction == usb.util.ENDPOINT_IN:
				in_endpoint = endpoint
			elif endpoint_direction == usb.util.ENDPOINT_OUT:
				out_endpoint = endpoint

		if not (in_endpoint and out_endpoint):
			raise Exception("cant find endpoints..")

		return HostDevice(
			in_endpoint=in_endpoint,
			out_endpoint=out_endpoint,
			tag=0x0  # its not important
		)

	def get_mount_point(self) -> Path | None:
		if not self.is_kernel_driver_active():
			# cant be mounted if kernel driver isnt active.
			return None

		if sys.platform == "darwin":
			process = subprocess.run(
				args=[
					"/usr/sbin/system_profiler",
					"-nospawn", "-xml",
					"SPUSBDataType",
					"-detailLevel", "full"
				],
				stdout=subprocess.PIPE
			)
			process.check_returncode()
			plist_data = process.stdout
			data = plistlib.loads(plist_data)[0]

			def find_device_data_within(data: dict) -> dict | None:
				# data has a key _items containing a list of either items or other dicts with the key _items.
				for sub_data in data["_items"]:
					if "_items" in sub_data:
						found_data = find_device_data_within(sub_data)
						if found_data:
							return found_data
					elif "serial_num" in sub_data:
						# the libusb address and macOS location id seem to differ after the device is reattached.
						# so i went with checking s/n instead.
						# Looking into it

						# this is a device and not a hub/controller so compare the location_id
						# location_id = sub_data["location_id"]
						# libusb_address = int(location_id.split("/")[1].strip())
						# if libusb_address == self.device.address:
						# 	# YAY WE FOUND IT ^w^
						# 	return sub_data

						if self.device.serial_number == sub_data["serial_num"]:
							# YAY WE FOUND IT ^w^
							return sub_data

				return None

			# recursively find the device
			this_device_data = find_device_data_within(data)
			if this_device_data is None:
				# noo .. we didnt find it ... T_T
				return

			media_data = this_device_data.get("Media")
			if media_data is None:
				# this device is attached but not mounted rn.
				return None

			for volume in media_data[0]["volumes"]:
				if "mount_point" in volume:
					return volume["mount_point"]
		else:
			raise NotImplementedError(f"not implemented on {sys.platform=}")

	def is_kernel_driver_active(self) -> bool:
		"""true if the kernel is attached to this device, like if its mounted as a mass storage device."""
		is_active = self.device.is_kernel_driver_active(self.mass_storage_interface.index)
		# print(f"{is_active=}")
		return is_active

	def detach_kernel_driver(self):
		"""forcefully detach the kernel driver for this device. ejecting it first is kinder to it."""
		# print("detached kernel driver")
		# print(f"{self.is_kernel_driver_active()=}")
		usb.util.dispose_resources(self.device)
		# print(f"{self.is_kernel_driver_active()=}")
		self.device.detach_kernel_driver(self.mass_storage_interface.index)
		# print(f"{self.is_kernel_driver_active()=}")

	def attach_kernel_driver(self):
		"""give the device back to the kernel . which will probably remount it."""
		# print("attached kernel driver")
		# print(f"{self.is_kernel_driver_active()=}")
		usb.util.release_interface(self.device, self.mass_storage_interface.index)
		# print(f"{self.is_kernel_driver_active()=}")
		self.device.attach_kernel_driver(self.mass_storage_interface.index)
		# print(f"{self.is_kernel_driver_active()=}")

	def __del__(self):
		# usb.util.dispose_resources(self.device)  # this is magic it makes it all work idk how but it does :3
		# print(f"Deleted: {id(self)}")
		pass

	def __enter__(self):
		# print("__enter__")
		# if self.is_kernel_driver_active():
		# 	self._kernel_driver_detached = True
		# self.detach_kernel_driver()
		pass

	def __exit__(self, exc_type, exc_val, exc_tb):
		# print("__exit__")
		# if self._kernel_driver_detached:
		# 	self.attach_kernel_driver()

		usb.util.dispose_resources(self.device)  # https://github.com/square/pyfu-usb/blob/master/pyfu_usb/dfu.py#L135
		pass


@dataclass(kw_only=True)
class iPodFirmwareSendState:
	block_number: int
	block_count: int | None = None
	# percentage: float | None = None


class iPodDeviceDFU(iPodDevice):
	def __init__(
			self,
			*,
			target: iPodTarget,
			device: usb.core.Device
	):
		super().__init__(
			target=target,
			device=device
		)

		self.dfu_host = DFUDevice(
			device=device,
			interface=0
		)

	def is_ready_for_firmware_block(self) -> bool:
		status = self.dfu_host.get_status()

		if status.state in [
			DFUDeviceState.IDLE,
			DFUDeviceState.DOWNLOAD_IDLE,
		]:
			return True
		return False

	def send_firmware_block(
		self,
		block_number: int,
		block: bytes
	):
		self.dfu_host.download(
			block_number=block_number,
			data=block
		)

	def send_firmware_termination_block(self, block_number: int):
		# indicate the firmware is over
		self.dfu_host.download(
			block_number=block_number,
			data=None
		)

	def is_firmware_upload_complete(self) -> bool:
		# returns True if the device is NOT responding to status queries (indicating it is rebooting) or is idle

		try:
			status = self.dfu_host.get_status()
		except usb.core.USBError:
			# this indicates completion, usually? because the iPod has rebooted it just totally stops responding
			return True

		if status.state in [
			DFUDeviceState.IDLE,
			DFUDeviceState.DOWNLOAD_IDLE,
		]:
			return True

		return False

	def send_firmware(
		self,
		stream: io.BytesIO,
		length: int,
		block_size: int = 0x800,
		on_progress: Optional[Callable[[iPodFirmwareSendState], None]] = None
	):
		block_number = 0
		block_count = math.ceil(length / block_size) if length else None

		stream.seek(block_size * block_number)
		for block in buffered(stream, buffer_size=block_size, limit=length):
			exception_count = 0
			is_last_block = block_number >= (block_count - 1)

			while True:
				try:
					self.send_firmware_block(
						block_number=block_number,
						block=block
					)
				except usb.core.USBError as exception:
					if is_last_block:
						# if there's an error on the last block, the device is done and probably rebooting.
						break

					# otherwise try to retry a few times until it works.
					exception_count += 1
					if exception_count > 5:
						raise exception

					continue

				break

			# do progress callback if specified
			if on_progress:
				on_progress(iPodFirmwareSendState(
					block_number=block_number,
					block_count=block_count,
					# percentage=(block_number / block_count) if block_count else None
				))

			# increment the block number
			block_number += 1

			# wait for device to become ready
			while True:
				if self.is_ready_for_firmware_block():
					break

		self.send_firmware_termination_block(block_number)
		if on_progress:
			on_progress(iPodFirmwareSendState(
				block_number=block_number,
				block_count=block_count,
				# percentage=1.0  # all done!
			))

		while True:
			if self.is_firmware_upload_complete():
				break

	def __enter__(self):
		self.dfu_host.__enter__()

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.dfu_host.__exit__(exc_type, exc_val, exc_tb)


class iPodDeviceWTF(iPodDeviceDFU):
	...
