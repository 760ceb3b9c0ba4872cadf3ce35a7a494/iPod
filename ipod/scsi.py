"""
implementation of a subset of the Small Computer System Interface (SCSI) protocol,
with support for proprietary Apple iPod subcommands.
Actual SCSI sending is platform-specific and is not implemented here.
"""

import io
from dataclasses import dataclass
from enum import Enum, IntEnum


class DataTransferDirection(Enum):
	"""Direction of SCSI data transfer."""
	NONE = "none"
	TO_DEVICE = "to_device"
	FROM_DEVICE = "from_device"
	BIDIRECTIONAL = "bidirectional"


class iPodSubcommand(IntEnum):
	"""Enumerates proprietary iPod subcommands"""
	# i refuse to call it "IPodSubcommand"
	UPDATE_START = 0x90
	UPDATE_CHUNK = 0x91
	UPDATE_END = 0x92
	REPARTITION = 0x94
	INFORMATION = 0x95
	UPDATE_FINALIZE = 0x31


class OperationCode(IntEnum):
	"""
	Enumerates a subset of SCSI operation codes.
	Only some operation codes are implemented here, see https://www.t10.org/lists/op-num.htm
	for a complete list.
	"""

	# group 0 - six-byte commands (00 to 1F)
	INQUIRY = 0x12
	PREVENT_ALLOW_MEDIUM_REMOVAL = 0x1E
	START_STOP_UNIT = 0x1B

	# group 1 - ten-byte commands (20 to 3F)
	READ_CAPACITY = 0x25
	READ_DEFECT_DATA = 0x37

	# group 2 - ten-byte commands (40 to 5F)
	LOG_SENSE = 0x4d

	# group 6 - vendor-specific
	IPOD = 0xC6  # iPod proprietary opcode


@dataclass()
class CommandDataBuffer:
	"""A SCSI command data buffer (CDB)"""
	operation_code: int
	"""SCSI operation code."""

	request: bytes
	"""OperationCode-specific request parameters"""

	service_action: int = None
	"""for certain CDB encodings, contains an additional qualification for the OperationCode."""

	control: int = 0
	"""contains common CDB metadata"""

	data_transfer_direction: DataTransferDirection = DataTransferDirection.NONE
	"""direction(s) of data transfer"""

	outgoing_data: bytes = None  # important difference!
	"""outgoing data, when `data_transfer_direction` is `TO_DEVICE` or `BIDIRECTIONAL`."""

	incoming_data_length: int = 0  # also important as wel
	"""length of incoming data, when `data_transfer_direction` is `FROM_DEVICE` or `BIDIRECTIONAL`."""

	def to_bytes(self) -> bytes:
		"""Convert this CDB to bytes"""
		if 0x00 <= self.operation_code < 0x20:
			# group 0 - six-byte commands (00 to 1F)
			if self.service_action is not None:
				raise Exception("ServiceAction field not available in CDB6")
			if len(self.request) != 4:
				raise Exception(
					f"CDB6 request size is {len(self.request)} bytes, needs to be 4 bytes without LengthField")

			buffer = io.BytesIO(bytes(6))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)
			buffer.write(bytes([self.control]))
			buffer.seek(0)
			return buffer.read()

		elif self.operation_code < 0x60:
			# group 1 (20 to 3F) and group 2 (40 to 5F) - ten-byte commands
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

		elif self.operation_code < 0x80:
			# group 3 - unimplemented stuff
			if self.operation_code == 0x7e:
				raise Exception("variable extended CDBs are unimplemented")
			elif self.operation_code == 0x7f:
				raise Exception("variable CDBs are unimplemented")
			else:
				raise Exception("OperationCode is reserved")

		elif self.operation_code < 0xa0:
			# group 4 - sixteen-byte commands (80 to 9F)
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
			# group 5 - twelve-byte commands (A0 to BF)

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

		elif self.operation_code == OperationCode.IPOD:
			# Apple proprietary opcode

			subcommand = self.request[0]
			if subcommand in {
				iPodSubcommand.UPDATE_START,
				iPodSubcommand.UPDATE_END,
				iPodSubcommand.UPDATE_FINALIZE,
				iPodSubcommand.REPARTITION,
				iPodSubcommand.INFORMATION
			}:
				limit = 15
			elif subcommand == iPodSubcommand.UPDATE_CHUNK:
				limit = 9
			elif subcommand == 0x96:
				# ipod_sun special command - https://freemyipod.org/wiki/Ipod_sun
				limit = 6
			else:
				raise Exception(f"cannot serialize subcommand {subcommand:x}")

			if len(self.request) > limit:
				raise Exception("request too long")

			buffer = io.BytesIO(bytes(limit + 1))
			buffer.write(bytes([self.operation_code]))
			buffer.write(self.request)  # this effectively pads the end with \x00
			buffer.seek(0)
			return buffer.read()

		raise ValueError(f"unhandled opcode 0x{self.operation_code:02x}")


def create_inquiry_vital_product_data(page_code: int, allocation_length: int) -> CommandDataBuffer:
	"""
	Build a SCSI INQUIRY Vital Product Data (VPD) CDB.

	Parameters:
		page_code: Page code of data to request
		allocation_length: Length of data to request
	"""

	buffer = io.BytesIO()
	# "When the EVPD bit is set to one, the PAGE CODE field specifies which page of vital product data information the device server shall return"
	buffer.write(0b00000001.to_bytes(1, "big"))
	buffer.write(page_code.to_bytes(1, "big"))
	buffer.write(allocation_length.to_bytes(2, "big"))
	buffer.seek(0)

	return CommandDataBuffer(
		operation_code=OperationCode.INQUIRY,
		request=buffer.read(),
		data_transfer_direction=DataTransferDirection.FROM_DEVICE,
		incoming_data_length=allocation_length
	)
