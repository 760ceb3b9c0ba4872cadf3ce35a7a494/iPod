"""
implementation of a subset of the USB Mass Storage protocol
"""
import errno
import io
import platform
from dataclasses import dataclass
from typing import Iterable

import usb.core

from .base import BaseSCSIDevice, BaseUSBProvider, ConnectedDevice
from ..definitions import USB_PID_INDEX, APPLE_VID
from ..dfu import DFUDevice
from ..scsi import CommandDataBuffer, DataTransferDirection
from ..utils import macOS_get_mount_point


@dataclass
class _CommandBlockWrapper:
	signature: bytes  # [4]byte
	tag: int
	data_transfer_length: int
	flags: int
	logical_unit_number: int
	# length: int
	command_block: bytes  # [16]byte

	def to_bytes(self) -> bytes:
		buffer = io.BytesIO(initial_bytes=bytes(31))
		buffer.write(self.signature)
		buffer.write(self.tag.to_bytes(4, "little"))
		buffer.write(self.data_transfer_length.to_bytes(4, "little"))
		buffer.write(self.flags.to_bytes(1, "little"))
		buffer.write(self.logical_unit_number.to_bytes(1, "little"))
		buffer.write(len(self.command_block).to_bytes(1, "little"))
		buffer.write(self.command_block)
		buffer.seek(0)
		a = buffer.read()
		return a


@dataclass
class _CommandStatusWrapper:
	signature: bytes  # [4]byte
	tag: int
	data_residue: int
	status: int

	@classmethod
	def from_bytes(cls, data: bytes):
		stream = io.BytesIO()
		stream.write(data)
		stream.seek(0)

		return cls(
			signature=stream.read(4),
			tag=int.from_bytes(stream.read(4), "little"),
			data_residue=int.from_bytes(stream.read(4), "little"),
			status=int.from_bytes(stream.read(1), "little")
		)


@dataclass
class _PyUSBSCSIDevice(BaseSCSIDevice):
	_tag: int
	_device: usb.core.Device
	_in_endpoint: usb.core.Endpoint
	_out_endpoint: usb.core.Endpoint

	def __init__(self, device_id: str):
		super().__init__()
		self._device_id = device_id
		self._tag = 0
		self._initialize_host()

	def _initialize_host(self):
		device = _id_to_pyusb_device(self._device_id)
		if device is None:
			raise ValueError("device is not connected")
		self._device = device
		configuration: usb.core.Configuration = device.get_active_configuration()

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

		self._in_endpoint = in_endpoint
		self._out_endpoint = out_endpoint

	def _build_cbw(self, cdb: CommandDataBuffer, data_length: int) -> _CommandBlockWrapper:
		data = cdb.to_bytes()
		if len(data) > 16:
			raise Exception("cdb data too long")

		# Bit 7 Direction - the device shall ignore this bit if the dCBWDataTransferLength field is zero, otherwise:
		# 0 = Data-Out from host to the device,
		# 1 = Data-In from the device to the host.
		if cdb.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			flags = 0b10000000
		elif cdb.data_transfer_direction in {DataTransferDirection.TO_DEVICE, DataTransferDirection.NONE}:
			flags = 0b00000000
		else:
			raise Exception("DataTransferDirection must be to or from device")

		self._tag += 1

		cbw = _CommandBlockWrapper(
			signature=b"USBC",
			tag=self._tag,
			data_transfer_length=data_length,
			flags=flags,
			logical_unit_number=0,
			command_block=data
		)

		return cbw

	def raw_command(self, cdb: CommandDataBuffer):
		cbw = self._build_cbw(
			cdb=cdb,
			data_length=(
				len(cdb.outgoing_data)
				if cdb.data_transfer_direction == DataTransferDirection.TO_DEVICE
				else cdb.incoming_data_length
			)
		)

		cbw_bytes = cbw.to_bytes()
		self._out_endpoint.write(cbw_bytes)

		read_data = None
		if cdb.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			read_data = self._in_endpoint.read(cdb.incoming_data_length)
			if len(read_data) != cdb.incoming_data_length:
				pass
		# print(f"warning: expected to read {cdb.incoming_data_length}, read {len(read_data)}")
		# raise Exception(f"expected to read {cdb.incoming_data_length}, read {len(read_data)}")
		elif cdb.data_transfer_direction == DataTransferDirection.TO_DEVICE:
			bytes_written = self._out_endpoint.write(cdb.outgoing_data)
			if bytes_written != len(cdb.outgoing_data):
				print(f"should've written {len(cdb.outgoing_data)} bytes, wrote {bytes_written}")
		else:
			pass

		csw_data = self._in_endpoint.read(13, timeout=32000)
		command_status_wrapper = _CommandStatusWrapper.from_bytes(csw_data)

		# "The signature field shall contain the value
		# 53425355h (little endian), indicating CSW"
		if command_status_wrapper.signature != b"USBS":
			raise Exception(f"expected signature {b'USBS'}, got {command_status_wrapper.signature}")
		if command_status_wrapper.tag != cbw.tag:
			raise Exception(f"tag mismatch!: {command_status_wrapper.tag=} {cbw.tag=}")
		if command_status_wrapper.data_residue != 0:
			# ugh this should make the data [:rlen-residue] but i cant without the length
			# print(f"DATA RESIDUE WARNING!!! {command_status_wrapper.data_residue=}")
			pass
		if command_status_wrapper.status != 0:
			raise Exception(f"err {command_status_wrapper.status=}")

		if cdb.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			return read_data

		return None

	def is_kernel_driver_active(self) -> bool:
		return self._device.is_kernel_driver_active(self.mass_storage_interface.index)

	def attach_kernel_driver(self) -> None:
		self._device.attach_kernel_driver(self.mass_storage_interface.index)

	def detach_kernel_driver(self) -> None:
		try:
			self._device.detach_kernel_driver(self.mass_storage_interface.index)
		except usb.core.USBError as error:
			if error.errno == errno.EACCES:
				raise PermissionError(str(error))
			raise error from None

	def get_mount_point(self) -> None:
		if not self.is_kernel_driver_active():
			# well if the kernel driver isn't active it can't be mounted!
			return None

		if platform.system() == "Darwin":
			return macOS_get_mount_point(self._device.serial_number)
		else:
			raise NotImplementedError("Unsupported on this platform")


def _pyusb_device_to_id(device: usb.core.Device) -> str:
	# this should accommodate 8 devices on one bus. sorry if u wanna use more than that
	return str((device.bus << 3) + device.port_number)


def _id_to_pyusb_device(device_id: str) -> usb.core.Device | None:
	device_id = int(device_id, 10)
	bus = device_id >> 3
	port_number = device_id & 0b111
	return usb.core.find(idVendor=APPLE_VID, bus=bus, port_number=port_number)


@dataclass
class PyUSBConnectedDevice(ConnectedDevice):
	bus: int
	address: int
	port_number: int


class PyUSBProvider(BaseUSBProvider):
	def list_connected_devices(self) -> Iterable[PyUSBConnectedDevice]:
		return [
			PyUSBConnectedDevice(
				id=_pyusb_device_to_id(device),
				target=USB_PID_INDEX[device.idProduct],
				serial=device.serial_number,
				bus=device.bus,
				address=device.address,
				port_number=device.port_number
			)
			for device in usb.core.find(find_all=True, idVendor=APPLE_VID)
			if device.idProduct in USB_PID_INDEX
		]

	def get_connected_device(self, device_id: str) -> PyUSBConnectedDevice | None:
		device = _id_to_pyusb_device(device_id)
		if not device:
			return None
		if device.idProduct not in USB_PID_INDEX:
			return None
		# noinspection PyUnresolvedReferences
		return PyUSBConnectedDevice(
			id=device_id,
			target=USB_PID_INDEX[device.idProduct],
			serial=device.serial_number,
			bus=device.bus,
			address=device.address,
			port_number=device.port_number
		)

	def get_scsi_device(self, device_id: str):
		return _PyUSBSCSIDevice(device_id)

	def get_dfu_device(self, device_id: str):
		return DFUDevice(device=_id_to_pyusb_device(device_id))
