"""
implementation of a subset of the Device Firmware Update (DFU) protocol
"""

from __future__ import annotations

import io
import typing
from dataclasses import dataclass
from enum import IntEnum

import usb.core
import usb.util

_DEFAULT_TIMEOUT_MS = 5000


class DFUDeviceStatus(IntEnum):
	OK = 0x00
	ERROR_TARGET = 0x01
	ERROR_FILE = 0x02
	ERROR_WRITE = 0x03
	ERROR_ERASE = 0x04
	ERROR_CHECK_ERASED = 0x05
	ERROR_PROGRAM = 0x06
	ERROR_VERIFY = 0x07
	ERROR_ADDRESS = 0x08
	ERROR_NOT_DONE = 0x09
	ERROR_FIRMWARE = 0x0A
	ERROR_VENDOR = 0x0B
	ERROR_USB_RESET = 0x0C
	ERROR_POWER_ON_RESET = 0x0D
	ERROR_UNKNOWN = 0x0E
	ERROR_STALLED_PACKET = 0x0F


class DFUDeviceState(IntEnum):
	# https://www.usb.org/sites/default/files/DFU_1.1.pdf
	APP_IDLE = 0x00
	APP_DETACH = 0x01
	IDLE = 0x02
	DOWNLOAD_SYNC = 0x03
	DOWNLOAD_BUSY = 0x04
	DOWNLOAD_IDLE = 0x05
	MANIFEST_SYNC = 0x06
	MANIFEST = 0x07
	MANIFEST_WAIT_RESET = 0x08
	UPLOAD_IDLE = 0x09
	ERROR = 0x0A


class DFUCommand(IntEnum):
	DETACH = 0
	DOWNLOAD = 1
	GET_STATUS = 3
	CLEAR_STATUS = 4
	GET_STATE = 5
	ABORT = 6


class USBRequestType(IntEnum):
	SEND = 0x21
	RECEIVE = 0xA1


@dataclass
class DFUDeviceStatusPayload:
	status: DFUDeviceStatus
	poll_timeout: int
	state: DFUDeviceState
	status_description_index: int  # "iString" is a stupid name

	@classmethod
	def from_stream(cls, stream: typing.BinaryIO) -> DFUDeviceStatusPayload:
		return cls(
			status=DFUDeviceStatus(stream.read(1)[0]),
			poll_timeout=int.from_bytes(stream.read(3), "little"),
			state=DFUDeviceState(stream.read(1)[0]),
			status_description_index=stream.read(1)[0]
		)


class DFUDevice:
	def __init__(self, device: usb.core.Device, interface: int = 0, *, timeout_ms: int = _DEFAULT_TIMEOUT_MS):
		self.device = device
		self.interface = interface
		self.timeout_ms = timeout_ms

	def get_status(self) -> DFUDeviceStatusPayload:
		data = self.device.ctrl_transfer(
			bmRequestType=USBRequestType.RECEIVE,
			bRequest=DFUCommand.GET_STATUS,
			wValue=0,
			wIndex=self.interface,
			data_or_wLength=6,  # _DFU_STATE_LEN
			timeout=self.timeout_ms,
		)

		return DFUDeviceStatusPayload.from_stream(io.BytesIO(data))

	def clear_status(self):
		self.device.ctrl_transfer(
			bmRequestType=USBRequestType.SEND,
			bRequest=DFUCommand.CLEAR_STATUS,
			wValue=0,
			wIndex=self.interface,
			data_or_wLength=None,
			timeout=self.timeout_ms,
		)

	def download(self, block_number: int, data: bytes | None):
		# pass data=None to end download
		self.device.ctrl_transfer(
			bmRequestType=USBRequestType.SEND,
			bRequest=DFUCommand.DOWNLOAD,
			wValue=block_number,  # % 0xFFFF,
			# official spec states that "It increments each time a block is transferred, wrapping to zero from 65,535."
			# but it looks like the iPod does not care
			wIndex=self.interface,
			data_or_wLength=data,
			timeout=self.timeout_ms,
		)

	def claim_interface(self):
		usb.util.claim_interface(self.device, self.interface)

	def release_interface(self):
		usb.util.release_interface(self.device, self.interface)

	def __enter__(self):
		pass
		# self.claim_interface()

	def __exit__(self, exc_type, exc_val, exc_tb):
		pass
		# self.release_interface()
