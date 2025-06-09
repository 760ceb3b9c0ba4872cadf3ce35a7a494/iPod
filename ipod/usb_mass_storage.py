"""
implementation of a subset of the USB Mass Storage protocol
"""

import io
from dataclasses import dataclass

import usb.core
from .scsi import CommandDataBuffer, DataTransferDirection, OperationCode


@dataclass
class CommandBlockWrapper:
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
class CommandStatusWrapper:
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
class HostDevice:
	in_endpoint: usb.core.Endpoint
	out_endpoint: usb.core.Endpoint
	tag: int

	def build_CBW(self, cbd: CommandDataBuffer, data_length: int) -> CommandBlockWrapper:
		data = cbd.to_bytes()
		if len(data) > 16:
			raise Exception("cbd data too long")

		# Bit 7 Direction - the device shall ignore this bit if the dCBWDataTransferLength field is zero, otherwise:
		# 0 = Data-Out from host to the device,
		# 1 = Data-In from the device to the host.
		if cbd.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			flags = 0b10000000
		elif cbd.data_transfer_direction in {DataTransferDirection.TO_DEVICE, DataTransferDirection.NONE}:
			flags = 0b00000000
		else:
			raise Exception("DataTransferDirection must be to or from device")

		self.tag += 1

		cbw = CommandBlockWrapper(
			signature=b"USBC",
			tag=self.tag,
			data_transfer_length=data_length,
			flags=flags,
			logical_unit_number=0,
			command_block=data
		)

		return cbw

	def raw_command(self, cbd: CommandDataBuffer):
		cbw = self.build_CBW(
			cbd=cbd,
			data_length=(
				len(cbd.outgoing_data)
				if cbd.data_transfer_direction == DataTransferDirection.TO_DEVICE
				else cbd.incoming_data_length
			)
		)

		cbw_bytes = cbw.to_bytes()
		self.out_endpoint.write(cbw_bytes)

		read_data = None
		if cbd.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			read_data = self.in_endpoint.read(cbd.incoming_data_length)
			if len(read_data) != cbd.incoming_data_length:
				pass
				# print(f"warning: expected to read {cbd.incoming_data_length}, read {len(read_data)}")
				# raise Exception(f"expected to read {cbd.incoming_data_length}, read {len(read_data)}")
		elif cbd.data_transfer_direction == DataTransferDirection.TO_DEVICE:
			bytes_written = self.out_endpoint.write(cbd.outgoing_data)
			if bytes_written != len(cbd.outgoing_data):
				print(f"should've written {len(cbd.outgoing_data)} bytes, wrote {bytes_written}")
		else:
			pass

		csw_data = self.in_endpoint.read(13, timeout=32000)
		command_status_wrapper = CommandStatusWrapper.from_bytes(csw_data)

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

		if cbd.data_transfer_direction == DataTransferDirection.FROM_DEVICE:
			return read_data

		return None

	def inquiry_vital_product_data(self, page_code: int, allocation_length: int) -> bytes:
		buffer = io.BytesIO()
		# "When the EVPD bit is set to one, the PAGE CODE field specifies which page of vital product data information the device server shall return"
		buffer.write(0b00000001.to_bytes(1, "big"))
		buffer.write(page_code.to_bytes(1, "big"))
		buffer.write(allocation_length.to_bytes(2, "big"))
		buffer.seek(0)

		cbd = CommandDataBuffer(
			operation_code=OperationCode.INQUIRY,
			request=buffer.read(),
			data_transfer_direction=DataTransferDirection.FROM_DEVICE,
			incoming_data_length=allocation_length
		)
		result = self.raw_command(cbd)
		return result[4:]
