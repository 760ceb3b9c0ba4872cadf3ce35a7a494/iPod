import re
import winreg
from typing import Iterable
from winreg import HKEY_LOCAL_MACHINE, REG_SZ

import usb.core
from wmi import WMI

from .base import ConnectedDevice, BaseSCSIDevice, BaseUSBProvider
from .win32_scsiio import Win32SCSIDev
from ..definitions import USB_PID_INDEX, APPLE_VID
from ..dfu import DFUDevice
from ..scsi import CommandDataBuffer

wmi = WMI()
USB_ID_REGEX = re.compile(r"^USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})\\(.+)$")
LOCATION_REGEX = re.compile(r"^Port_#(\d{4})\.Hub_#(\d{4})$")


class _Win32SCSIDevice(BaseSCSIDevice):
	def __init__(self, device_path: str):
		self._device = Win32SCSIDev(path=device_path)

	def raw_command(self, cdb: CommandDataBuffer) -> bytes | None:
		return_buffer = bytearray(cdb.incoming_data_length)
		self._device.execute(
			cdb=cdb.to_bytes(),
			data_out=cdb.outgoing_data,
			data_in=return_buffer
		)

		if cdb.incoming_data_length:
			return bytes(return_buffer)

		return None


def _location_information_to_id(location: str) -> str:
	match_2 = LOCATION_REGEX.match(location)
	if not match_2:
		raise ValueError
	port_id = int(match_2[1])
	hub_id = int(match_2[2])
	return str((hub_id << 3) + port_id)


def _id_to_location_information(device_id: str) -> str:
	device_id = int(device_id, 10)
	hub_id = device_id >> 3
	port_id = device_id & 0b111
	return f"Port_#{port_id:04}.Hub_#{hub_id:04}"


class Win32USBProvider(BaseUSBProvider):
	# inherits the list_usb_devices

	def list_connected_devices(self) -> Iterable[ConnectedDevice]:
		for controller_object in wmi.Win32_USBControllerDevice():
			pnp_device_object = controller_object.Dependent
			raw_device_id = pnp_device_object.DeviceID
			match = USB_ID_REGEX.match(raw_device_id)
			if not match:
				continue

			vendor_id, product_id, serial = int(match[1], 16), int(match[2], 16), match[3]
			if vendor_id != APPLE_VID:
				continue

			if product_id not in USB_PID_INDEX:
				continue

			# now we have the device but we need its location. that's not in the Win32_USBHub data,
			# i need to query the registry. why? i don't know.
			with winreg.OpenKeyEx(HKEY_LOCAL_MACHINE, fr"SYSTEM\CurrentControlSet\Enum\{raw_device_id}") as key:
				location_information, value_type = winreg.QueryValueEx(key, "LocationInformation")
				assert value_type == REG_SZ

				device_id = _location_information_to_id(location_information)

			yield ConnectedDevice(
				id=device_id,
				target=USB_PID_INDEX[product_id],
				serial=serial
			)

	def get_connected_device(self, device_id: str) -> ConnectedDevice | None:
		# i can't find a faster way to do this.
		for connected_device in self.list_connected_devices():
			if connected_device.id == device_id:
				return connected_device
		return None

	def get_scsi_device(self, device_id: str):
		connected_device = self.get_connected_device(device_id)

		target_drive_object = None
		for drive_object in wmi.instances("Win32_DiskDrive"):
			pnp_device_id = drive_object.PNPDeviceID
			if pnp_device_id.startswith("USBSTOR\\") and connected_device.serial in pnp_device_id:
				target_drive_object = drive_object
				break

		if target_drive_object is None:
			raise ValueError("could not find device disk drive")

		target_logical_disk = None
		for partition in target_drive_object.associators(wmi_result_class="Win32_DiskPartition"):
			for logical_disk in partition.associators(wmi_result_class="Win32_LogicalDisk"):
				target_logical_disk = logical_disk
				break

		if target_logical_disk is None:
			raise ValueError("could not find logical disk")

		# target_logical_disk.Name is a drive letter like F:

		scsi_device_path = rf"\\.\{target_logical_disk.Name}"  # like \\.\F:
		return _Win32SCSIDevice(scsi_device_path)

	def get_dfu_device(self, device_id: str):
		# Minor PyUSB implementation for win32 just for DFU.
		connected_device = self.get_connected_device(device_id)
		pyusb_device = usb.core.find(idVendor=APPLE_VID, serial_number=connected_device.serial)
		return DFUDevice(pyusb_device)
