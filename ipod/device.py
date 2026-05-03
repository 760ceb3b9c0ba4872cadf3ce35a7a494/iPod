"""
implementation of the Device Firmware Update (DFU) protocol
"""

from __future__ import annotations

import io
import math
import platform
import zlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Iterable

import usb.core

from .definitions import iPodTarget, iPodMode, iPodModel
from .dfu import DFUDevice, DFUDeviceState
from .platforms.base import BaseSCSIDevice, BaseUSBProvider, ConnectedDevice
from .plist import iPodPlistParser
from .scsi import CommandDataBuffer, iPodSubcommand, DataTransferDirection
from .utils import buffered


@dataclass()
class iPodDevice:
	target: iPodTarget


class iPodUpdateKind(Enum):
	BOOTLOADER = "bootloader"
	FIRMWARE = "firmware"


class iPodProvider:
	_usb_provider: BaseUSBProvider

	def __enter__(self):
		return self

	def __init__(
			self,
			usb_provider: BaseUSBProvider | None = None
	):
		if usb_provider is None:
			system = platform.system()
			if system == "Windows":
				# windows provider
				from .platforms.win32_provider import Win32USBProvider
				usb_provider = Win32USBProvider()
			elif system == "Linux":
				# linux provider
				from .platforms.sgutils_provider import SGUtilsUSBProvider
				usb_provider = SGUtilsUSBProvider()
			else:
				# pyusb provider (kinda the fallback)
				from .platforms.pyusb_provider import PyUSBProvider
				usb_provider = PyUSBProvider()

		self._usb_provider = usb_provider

	def list_devices(self) -> Iterable[ConnectedDevice]:
		return self._usb_provider.list_connected_devices()

	def get_device(self, device: str | ConnectedDevice):
		if isinstance(device, str):
			connected_device = self._usb_provider.get_connected_device(device)
			if not connected_device:
				return None
		else:
			connected_device = device

		return self._get_device(connected_device)

	def _get_device(self, raw_device: ConnectedDevice) -> iPodDeviceDFU | iPodDeviceDiskMode | None:
		if raw_device.target.mode in {iPodMode.DFU, iPodMode.WTF}:
			return iPodDeviceDFU(
				target=raw_device.target,
				dfu_host=self._usb_provider.get_dfu_device(raw_device.id)
			)
		elif raw_device.target.mode == iPodMode.DISK:
			return iPodDeviceDiskMode(
				target=raw_device.target,
				device=self._usb_provider.get_scsi_device(raw_device.id)
			)

		return None


class iPodDeviceDiskMode(iPodDevice):
	def __init__(
			self,
			*,
			target: iPodTarget,
			device: BaseSCSIDevice
	):
		super().__init__(target=target)
		self._device = device

	def get_device_information_raw(self):
		self._device.inquiry_vital_product_data(0xc0, 0xfc)
		stream = io.BytesIO()
		for page in range(0xc2, 0xff):
			data = self._device.inquiry_vital_product_data(page, 0xfc)
			stream.write(data)
			if len(data) < 0xfc - 4:
				break
		stream.seek(0)
		return stream.read()

	def test(self):
		self._device.inquiry_vital_product_data(0x0, 0x10)

	def get_device_information(self):
		data = self.get_device_information_raw()
		decoded_data = iPodPlistParser(dict_type=dict).parse(io.BytesIO(data))
		return decoded_data

	def eject(self):
		"""
		Tell the iPod that it is "OK to Disconnect". Also reboots an iPod after an update.
		"""
		# thank you so, so, so, so much. https://ramblings.narrabilis.com/ejecting-ipod-under-linux
		self._device.raw_command(CommandDataBuffer(
			operation_code=0x1E,  # "PREVENT ALLOW MEDIUM REMOVAL"
			request=bytes([0, 0, 0, 0])
		))
		self._device.raw_command(CommandDataBuffer(
			operation_code=0x1b,  # "START STOP UNIT"
			request=bytes([
				0b0000_0001,  # IMMED = 1
				0b0000_0000,
				0b0000_0000,
				0b0000_0010  # LOEJ = 1
			])
		))

	def get_capacity(self) -> tuple[int, int]:
		# returns: block count, block size
		data = self._device.raw_command(CommandDataBuffer(
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
		self._device.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=stream.read(),
		))

	def _update_end(self):
		self._device.raw_command(CommandDataBuffer(
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
		self._device.raw_command(CommandDataBuffer(
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

		self._device.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=request_stream.read(),
			outgoing_data=content,
			data_transfer_direction=DataTransferDirection.TO_DEVICE
		))

	def finalize_updates(self):
		self._device.raw_command(CommandDataBuffer(
			operation_code=0xc6,
			request=bytes([iPodSubcommand.UPDATE_FINALIZE])  # i think the "LOEJ" bit was set
		))

	def update(
			self,
			kind: iPodUpdateKind,
			stream: BinaryIO,
			length: int,
			block_size: int = 0x8000,
			on_progress: Optional[Callable[[iPodFirmwareSendState], None]] = None
	):
		self._update_start(kind, length)
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

	def get_mount_point(self) -> Path | None:
		return self._device.get_mount_point()

	def is_kernel_driver_active(self):
		return self._device.is_kernel_driver_active()

	def detach_kernel_driver(self):
		return self._device.detach_kernel_driver()

	def attach_kernel_driver(self):
		return self._device.attach_kernel_driver()


@dataclass()
class iPodFirmwareSendState:
	block_number: int
	block_count: int | None = None


class iPodDeviceDFU(iPodDevice):
	def __init__(
			self,
			*,
			target: iPodTarget,
			dfu_host: DFUDevice
	):
		super().__init__(target=target)

		self.dfu_host = dfu_host

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
			stream: BinaryIO,
			length: int,
			block_size: int = 0x800,
			on_progress: Optional[Callable[[iPodFirmwareSendState], None]] = None
	):
		include_checksum = self.target.model == iPodModel.NANO_3G  # nano 3g requires a checksum
		start_offset = stream.tell()

		if include_checksum:
			# TODO: maybe do this without allocating a new buffer. idk. does it matter. computers are fast now
			new_stream = io.BytesIO()
			crc_value = 0  # a tool that will help us later :3
			for block in buffered(stream, buffer_size=0x10000, limit=length):
				new_stream.write(block)
				crc_value = zlib.crc32(block, crc_value)

			crc = int.to_bytes(crc_value, 4, "little")
			new_stream.write(bytes([byte ^ 0xFF for byte in crc]))  # sneaky you itunes :3

			stream.seek(start_offset)  # goodbye old one

			length = new_stream.tell()
			new_stream.seek(0)
			stream = new_stream

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
					block_count=block_count
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
				block_count=block_count
			))

		while True:
			if self.is_firmware_upload_complete():
				break
