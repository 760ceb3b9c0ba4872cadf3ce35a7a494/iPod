from enum import IntEnum

from .device import iPodDeviceDiskMode
from .scsi import CommandDataBuffer, DataTransferDirection, OperationCode


class _iPodSunRequestMode(IntEnum):
	WRITE = 0x01
	READ = 0x02
	CALL = 0x03


def _make_request(mode: _iPodSunRequestMode, address: int) -> bytes:
	return bytes([0x96, mode]) + int.to_bytes(address, 4, "big")


class iPodSunDevice:
	"""
	represents an iPod in disk mode that's been pwned by ipod_sun (https://github.com/CUB3D/ipod_sun)
	"""
	def __init__(self, device: iPodDeviceDiskMode):
		if not isinstance(device, iPodDeviceDiskMode):
			raise ValueError("not a disk mode iPod :(")

		self._scsi_device = device._device

	def memory_read(self, address: int, length: int) -> bytes:
		return self._scsi_device.raw_command(CommandDataBuffer(
			operation_code=OperationCode.IPOD,
			request=_make_request(_iPodSunRequestMode.READ, address),
			data_transfer_direction=DataTransferDirection.FROM_DEVICE,
			incoming_data_length=length
		))

	def memory_call(self, address: int):
		return self._scsi_device.raw_command(CommandDataBuffer(
			operation_code=OperationCode.IPOD,
			request=_make_request(_iPodSunRequestMode.CALL, address)
		))

	def memory_write(self, address: int, data: bytes):
		self._scsi_device.raw_command(CommandDataBuffer(
			operation_code=OperationCode.IPOD,
			request=_make_request(_iPodSunRequestMode.WRITE, address),
			data_transfer_direction=DataTransferDirection.TO_DEVICE,
			outgoing_data=data
		))

