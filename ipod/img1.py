"""
implementation of the MSE file format, used to store a list of IMG1 firmware partitions.
"""

from .definitions import iPodSoC
from dataclasses import dataclass
from typing import BinaryIO
from enum import Enum

from .utils import buffered_copy


class IMG1Version(Enum):
	# v1 = "1.0"
	v2 = "2.0"


class IMG1SignatureFormat(Enum):
	# SIGNED_ENCRYPTED = 1
	# SIGNED = 2
	X509_SIGNED_ENCRYPTED = 3
	X509_SIGNED = 4


@dataclass
class IMG1Header:
	soc: iPodSoC
	version: IMG1Version
	signature_format: IMG1SignatureFormat
	entry_point: int
	body_length: int
	data_length: int
	footer_offset: int
	footer_length: int
	salt: int
	unk0: int
	unk1: int
	header_signature: bytes
	header_leftover: bytes

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		try:
			soc = iPodSoC(stream.read(4).decode("ascii"))
		except ValueError:
			raise ValueError("unknown or invalid IMG1")

		return cls(
			soc=soc,
			version=IMG1Version(stream.read(3).decode("ascii")),
			signature_format=IMG1SignatureFormat(stream.read(1)[0]),
			entry_point=int.from_bytes(stream.read(4), "little"),  # (relative to header end)
			body_length=int.from_bytes(stream.read(4), "little"),
			data_length=int.from_bytes(stream.read(4), "little"),  # inferred
			footer_offset=int.from_bytes(stream.read(4), "little"),  # inferred
			footer_length=int.from_bytes(stream.read(4), "little"),
			salt=int.from_bytes(stream.read(32), "little"),
			unk0=int.from_bytes(stream.read(2), "little"),
			unk1=int.from_bytes(stream.read(2), "little"),
			header_signature=stream.read(16),
			header_leftover=stream.read(4),
		)


class IMG1:
	def __init__(self, stream: BinaryIO):
		self.stream = stream
		self._start = stream.tell()
		self.header = IMG1Header.from_stream(stream)

	def _seek(self, offset: int):
		self.stream.seek(self._start + offset)

	def _data_offset(self):
		if self.header.soc in {iPodSoC.S5L8723, iPodSoC.S5L8740}:
			return 0x400
		else:
			return 0x600

	def read_body(self) -> bytes:
		self._seek(self._data_offset())
		return self.stream.read(self.header.body_length)

	def write_body_to_stream(self, stream: BinaryIO):
		if self.header.body_length > 0x1000000:
			# for files larger than 16 MB use chunked copying
			buffered_copy(
				source=self.stream,
				destination=stream,
				limit=self.header.body_length
			)
		else:
			stream.write(self.read_body())

	def read_signature(self) -> bytes:
		self._seek(self._data_offset() + self.header.body_length)
		return self.stream.read(0x80)

	def read_certificate(self) -> bytes:
		self._seek(self._data_offset() + self.header.footer_offset)
		return self.stream.read(self.header.footer_length)
