"""
implementation of a subset of the USB SCSI protocol with Apple iPodSubcommand extensions
"""

import io
from dataclasses import dataclass
from enum import Enum, IntEnum


class DataTransferDirection(Enum):
	NONE = "none"
	TO_DEVICE = "to_device"
	FROM_DEVICE = "from_device"
	BIDIRECTIONAL = "bidirectional"


class iPodSubcommand(IntEnum):
	# i refuse to call it "IPodSubcommand"
	UPDATE_START = 0x90
	UPDATE_CHUNK = 0x91
	UPDATE_END = 0x92
	REPARTITION = 0x94
	UPDATE_FINALIZE = 0x31


class OperationCode(IntEnum):
	INQUIRY = 0x12
	READ_DEFECT_DATA = 0x37
	LOG_SENSE = 0x4d


@dataclass()
class CommandDataBuffer:
	operation_code: int

	request: bytes  # Request contains the OperationCode-specific request parameters

	# ServiceAction can (for certain CDB encodings) contain an additional
	# qualification for the OperationCode.
	service_action: int = None

	# Control contains common CDB metadata
	control: int = 0

	# DataTransferDirection contains the direction(s) of the data transfer(s)
	# to be made.
	data_transfer_direction: DataTransferDirection = DataTransferDirection.NONE

	outgoing_data: bytes = None  # important difference!
	incoming_data_length: int = 0  # also important as wel

	def to_bytes(self) -> bytes:
		if self.operation_code < 0x20:
			# print(f"Sending CDB6 {self.operation_code=}")
			if self.service_action is not None:
				raise Exception("ServiceAction field not available in CDB6")
			if len(self.request) != 4:
				raise Exception(f"CDB6 request size is {len(self.request)} bytes, needs to be 4 bytes without LengthField")

			buffer = io.BytesIO(bytes(6))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)
			buffer.write(bytes([self.control]))
			buffer.seek(0)
			return buffer.read()
		elif self.operation_code < 0x60:
			# print(f"Sending CDB10 {self.operation_code=}")
			if len(self.request) != 8:
				raise Exception(f"CDB10 request size is {len(self.request)} bytes, needs to be 8")  # its 8, right?

			buffer = io.BytesIO(bytes(10))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)
			buffer.write(bytes([self.control]))

			if self.service_action is not None:
				buffer.seek(1)
				value = buffer.read(1)[0]
				buffer.write(bytes([value | self.service_action & 0b11111]))

			buffer.seek(0)
			return buffer.read()
		elif self.operation_code < 0x7e:
			raise Exception("OperationCode is reserved")
		elif self.operation_code == 0x7e:
			raise Exception("variable extended CDBs are unimplemented")
		elif self.operation_code == 0x7f:
			raise Exception("variable CDBs are unimplemented")
		elif self.operation_code < 0xa0:
			# print(f"Sending CDB16 {self.operation_code=}")
			if len(self.request) != 14:
				raise Exception(f"CDB16 request size is {len(self.request)} bytes, needs to be 14")

			# ok this is a lot of code dupe im gonna need to fix this!!!
			buffer = io.BytesIO(bytes(16))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)
			buffer.write(bytes([self.control]))

			if self.service_action is not None:
				buffer.seek(1)
				value = buffer.read(1)[0]
				buffer.write(bytes([value | self.service_action & 0b11111]))

			buffer.seek(0)
			return buffer.read()
		elif self.operation_code < 0xc0:
			# print(f"Sending CDB12 {self.operation_code=}")
			if len(self.request) != 10:
				raise Exception(f"CDB12 request size is {len(self.request)} bytes, needs to be 10")

			buffer = io.BytesIO(bytes(12))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)
			buffer.write(bytes([self.control]))

			if self.service_action is not None:
				buffer.seek(1)
				value = buffer.read(1)[0]
				buffer.write(bytes([value | self.service_action & 0b11111]))

			buffer.seek(0)
			return buffer.read()
		elif self.operation_code == 0xc6:
			limit = 5  # idk why 5 but thats what wInd3x does so
			subcommand = self.request[0]
			if subcommand in {
				iPodSubcommand.UPDATE_START,
				iPodSubcommand.UPDATE_END,
				iPodSubcommand.UPDATE_FINALIZE,
				iPodSubcommand.REPARTITION,
			}:
				limit = 15
			elif subcommand == iPodSubcommand.UPDATE_CHUNK:
				limit = 9
			else:
				raise Exception(f"cannot serialize subcommand {subcommand:x}")

			if len(self.request) > limit:
				raise Exception("request too long")

			buffer = io.BytesIO(bytes(limit+1))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)  # this effectively pads the end with \x00
			buffer.seek(0)
			return buffer.read()

		raise ValueError(f"unhandled opcode {self.operation_code}")
