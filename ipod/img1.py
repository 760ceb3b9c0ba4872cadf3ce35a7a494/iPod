"""
implementation of the IMG1 file format, used to store iPod software.
Technical details at https://freemyipod.org/wiki/IMG1
"""
from __future__ import annotations

import dataclasses
import io
from dataclasses import dataclass
from enum import Enum
from typing import BinaryIO, Optional

from .definitions import iPodSoC
from .utils import buffered_copy


class IMG1Version(Enum):
	"""Enumerates versions of the IMG1 format."""
	# v1 = "1.0"
	v2 = "2.0"
	"""Version 2, used by the iPod nano (4th generation) and newer"""


class IMG1SignatureFormat(Enum):
	"""Enumerates possible signature formats of an IMG1 file."""
	# SIGNED_ENCRYPTED = 1
	# SIGNED = 2
	X509_SIGNED_ENCRYPTED = 3
	"""Signed and encrypted with an [X.509](https://en.wikipedia.org/wiki/X.509) certificate in DER format."""
	X509_SIGNED = 4
	"""Signed with an [X.509](https://en.wikipedia.org/wiki/X.509) certificate in DER format, unencrypted."""


@dataclass(kw_only=True)
class IMG1Parameters:
	"""IMG1 file parameters."""
	soc: iPodSoC
	"""SoC targeted by this IMG1."""
	version: IMG1Version = IMG1Version.v2
	"""Version of this IMG1 file."""
	signature_format: IMG1SignatureFormat
	"""Version of this IMG1 file."""
	entry_point: int = 0
	"""Entry point address within the IMG1 body. Usually unused."""
	salt: int = 0
	"""Salt used by this IMG1."""
	unk0: int = 0
	"""Unknown field, usually zero."""
	unk1: int = 0
	"""Unknown field, usually zero."""
	header_signature: bytes = bytes(16)
	"""AES-encrypted SHA1 signature of the IMG1 body."""
	header_leftover: bytes = bytes(4)
	"""4 bytes of leftover SHA1 digest; see [leftover SHA in header](https://freemyipod.org/wiki/IMG1#Leftover_SHA_in_header)"""


@dataclass(kw_only=True)
class IMG1Header(IMG1Parameters):
	"""Header of an IMG1 file."""
	body_length: int
	"""Length of the body, in bytes"""
	data_length: int
	"""Length of the data (body plus signature plus certificate) in bytes"""
	footer_offset: int
	"""Offset of the footer (certificate)"""
	footer_length: int
	"""Length of the footer (certificate)"""

	def to_stream(self, stream: BinaryIO):
		"""Write the header out to a stream."""
		stream.write(self.soc.value.encode("ascii"))
		stream.write(self.version.value.encode("ascii"))
		stream.write(self.signature_format.value.to_bytes(1, "little"))
		stream.write(self.entry_point.to_bytes(4, "little"))
		stream.write(self.body_length.to_bytes(4, "little"))
		stream.write(self.data_length.to_bytes(4, "little"))
		stream.write(self.footer_offset.to_bytes(4, "little"))
		stream.write(self.footer_length.to_bytes(4, "little"))
		stream.write(self.salt.to_bytes(32, "little"))
		stream.write(self.unk0.to_bytes(2, "little"))
		stream.write(self.unk1.to_bytes(2, "little"))
		stream.write(self.header_signature)
		stream.write(self.header_leftover)

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		"""Parse header from a stream."""
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


def looks_like_img1(stream: BinaryIO) -> bool:
	"""Determines if a stream looks like it contains IMG1 data."""
	four_chars = stream.read(4)
	stream.seek(-len(four_chars), io.SEEK_CUR)
	try:
		iPodSoC(four_chars.decode("ascii"))
	except (ValueError, UnicodeDecodeError):
		return False

	return True


def _body_offset_for_soc(soc: iPodSoC):
	if soc in {iPodSoC.S5L8723, iPodSoC.S5L8740}:
		return 0x400
	else:
		return 0x600


class IMG1:
	"""Represents an IMG1 file."""
	def __init__(self, stream: BinaryIO):
		self.stream: BinaryIO = stream
		self._start = stream.tell()
		self._header = None

	@property
	def header(self) -> IMG1Header:
		"""Header of the IMG1"""
		return self._header

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		"""Construct an IMG1 from a stream."""
		self = cls(stream)
		self._read_header()
		return self

	@classmethod
	def from_parts(
			cls,
			stream: BinaryIO,
			*,
			parameters: IMG1Parameters,
			body_stream: BinaryIO,
			body_length: Optional[int] = None,
			signature_data: bytes,
			certificate_data: bytes,
	) -> IMG1:
		"""
		Construct a new IMG1 from parts.
		Parameters:
			stream: Output stream
			parameters: IMG1 parameters
			body_stream: Stream containing the new IMG1 body
			body_length: Length of the new body
			signature_data: Signature data
			certificate_data: Certificate data
		"""
		if body_length is None:
			body_stream.seek(0, io.SEEK_END)
			body_length = body_stream.tell()
			body_stream.seek(0)

		header = IMG1Header(
			**dataclasses.asdict(parameters),
			body_length=body_length,
			data_length=body_length + len(signature_data) + len(certificate_data),
			footer_offset=body_length + len(signature_data),
			footer_length=len(certificate_data)
		)
		self = cls(stream)
		self.write_header(header)
		self.write_body_from_stream(body_stream)
		self.write_signature(signature_data)
		self.write_certificate(certificate_data)
		return self

	def copy_from(self, other: IMG1):
		"""Copies from another IMG1."""
		self.write_header(other.header)
		self.write_signature(other.read_signature())
		self.write_certificate(other.read_certificate())
		# minimize allocation:
		other._seek(other._body_offset())
		self.write_body_from_stream(other.stream)

	def _seek(self, offset: int):
		self.stream.seek(self._start + offset)

	def _body_offset(self):
		return _body_offset_for_soc(self.header.soc)

	def _read_header(self) -> IMG1Header:
		self._seek(0)
		self._header = IMG1Header.from_stream(self.stream)
		return self._header

	def write_header(self, header: IMG1Header):
		"""Write a new IMG1 header."""
		self._seek(0)
		header.to_stream(self.stream)
		self._header = header

	def read_body(self) -> bytes:
		"""Read the entire body of this IMG1."""
		self._seek(self._body_offset())
		return self.stream.read(self._header.body_length)

	def write_body(self, data: bytes):
		"""Write a new body to this IMG1. Must match the `body_length` specified in the header."""
		if len(data) != self._header.body_length:
			raise ValueError("body is the wrong length")
		self._seek(self._body_offset())
		self.stream.write(data)

	def write_body_from_stream(self, stream: BinaryIO):
		"""Write a new body to this IMG1 from a stream."""
		self._seek(self._body_offset())
		if self._header.body_length > 0x1_000_000:
			# for files larger than 16 MB use chunked copying
			buffered_copy(
				source=self.stream,
				destination=stream,
				limit=self._header.body_length
			)
		else:
			self.write_body(stream.read(self._header.body_length))

	def read_body_to_stream(self, stream: BinaryIO):
		"""Read the body of this IMG1 to a stream."""
		if self._header.body_length > 0x1_000_000:
			# for files larger than 16 MB use chunked copying
			buffered_copy(
				source=self.stream,
				destination=stream,
				limit=self._header.body_length
			)
		else:
			stream.write(self.read_body())

	def read_signature(self) -> bytes:
		"""Read the signature of this IMG1."""
		self._seek(self._body_offset() + self._header.body_length)
		return self.stream.read(0x80)

	def write_signature(self, data: bytes):
		"""Write a new signature to this IMG1."""
		self._seek(self._body_offset() + self._header.body_length)
		self.stream.write(data)

	def read_certificate(self) -> bytes:
		"""Read the certificate of this IMG1."""
		self._seek(self._body_offset() + self._header.footer_offset)
		return self.stream.read(self._header.footer_length)

	def write_certificate(self, data: bytes):
		"""Write a new certificate to this IMG1."""
		self._seek(self._body_offset() + self._header.footer_offset)
		self.stream.write(data)
