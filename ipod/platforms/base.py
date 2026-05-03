from dataclasses import dataclass
from typing import Iterable

from ..definitions import iPodTarget
from ..dfu import DFUDevice
from ..scsi import CommandDataBuffer, create_inquiry_vital_product_data


class BaseSCSIDevice:
	"""
	this is an abstract class representing a SCSI device that can take a SCSI command
	"""

	def raw_command(self, cdb: CommandDataBuffer) -> bytes | None: ...

	def inquiry_vital_product_data(self, page_code: int, allocation_length: int) -> bytes:
		cdb = create_inquiry_vital_product_data(page_code=page_code, allocation_length=allocation_length)
		data = self.raw_command(cdb)
		length = data[3]
		return data[4:4 + length]

	def is_kernel_driver_active(self) -> bool: ...

	def attach_kernel_driver(self) -> None: ...

	def detach_kernel_driver(self) -> None: ...

	def get_mount_point(self) -> None: ...


@dataclass
class ConnectedDevice:
	id: str
	serial: str
	target: iPodTarget


class BaseUSBProvider:
	def list_connected_devices(self) -> Iterable[ConnectedDevice]: ...

	def get_connected_device(self, device_id: str) -> ConnectedDevice | None: ...

	def get_scsi_device(self, device_id: str) -> BaseSCSIDevice:  ...

	def get_dfu_device(self, device_id: str) -> DFUDevice:  ...
