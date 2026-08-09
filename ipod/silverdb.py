import abc
import math
import struct
from dataclasses import dataclass
from enum import Enum
from typing import BinaryIO, NamedTuple, Type, Optional

import PIL.Image
from PIL import Image

from ipod.utils import read_null_terminated_string, pixel_fromBGRA, pixels_from565, pixel_toBGRA, pixel_to565


@dataclass
class _SilverDBSectionHeader:
	"""Represents the raw header of a section in a SilverDB."""
	type: str
	resource_count: int
	jumpy: bool
	offset: int

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		return cls(
			type=stream.read(4).decode("ascii")[::-1],
			resource_count=int.from_bytes(stream.read(4), "little"),
			jumpy=bool.from_bytes(stream.read(4)),
			offset=int.from_bytes(stream.read(4), "little")
		)

	def to_stream(self, stream: BinaryIO):
		stream.write(self.type.encode("ascii")[::-1])
		stream.write(self.resource_count.to_bytes(4, "little"))
		stream.write(self.jumpy.to_bytes(4, "little"))
		stream.write(self.offset.to_bytes(4, "little"))


@dataclass
class _SilverDBResourceHeader:
	"""Represents the raw header of a single resource in a SilverDB."""
	id: int
	offset: int
	length: int

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		return cls(
			id=int.from_bytes(stream.read(4), "little"),
			offset=int.from_bytes(stream.read(4), "little"),
			length=int.from_bytes(stream.read(4), "little"),
		)

	def to_stream(self, stream: BinaryIO):
		stream.write(self.id.to_bytes(4, "little"))
		stream.write(self.offset.to_bytes(4, "little"))
		stream.write(self.length.to_bytes(4, "little"))


@dataclass
class SilverDBResource(abc.ABC):
	"""Base class inherited by all SilverDB resource types."""
	id: int

	@classmethod
	@abc.abstractmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int): ...

	@abc.abstractmethod
	def to_stream(self, stream: BinaryIO): ...


class Color(NamedTuple):
	"""Represents an RGBA8888 color."""
	r: int
	g: int
	b: int
	a: int

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		return cls(*stream.read(4))

	def to_stream(self, stream: BinaryIO):
		stream.write(bytes(self))


@dataclass
class ColorResource(SilverDBResource):
	"""Represents a color (COLR) resource within a SilverDB."""
	color: Color

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		return cls(id=id, color=Color.from_stream(stream))

	def to_stream(self, stream: BinaryIO):
		self.color.to_stream(stream)


@dataclass
class CLovResourceEntry:
	"""Represents an entry within a SilverDB CLov resource."""

	idk: bytes
	unk_1: int
	some_id: int
	another_id: Optional[int]

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		length = int.from_bytes(stream.read(4), "little")
		some_id = int.from_bytes(stream.read(4), "little")
		maybe_mode = int.from_bytes(stream.read(4), "little")
		print(f"{maybe_mode=}")

		more_length = int.from_bytes(stream.read(4), "little")
		print(f"{more_length=}")
		if maybe_mode in {2, 3}:
			idk = stream.read(more_length)
			another_id = int.from_bytes(stream.read(4), "little")
			if maybe_mode == 3:
				assert int.from_bytes(stream.read(4), "little") == 3
				idk_2 = stream.read(4)
				print(f"{idk_2=}")
				assert int.from_bytes(stream.read(4), "little") == 512

			assert int.from_bytes(stream.read(4), "little") == 4

		else:
			idk = b""
			another_id = None

		assert stream.read(4)[::-1] == b"SORC"
		unk_1 = int.from_bytes(stream.read(4), "little")

		return cls(idk=idk, unk_1=unk_1, some_id=some_id, another_id=another_id)

	def to_stream(self, stream: BinaryIO):
		...


@dataclass
class CLovResource(SilverDBResource):
	"""Represents a CLov resource within a SilverDB. TODO: what is CLov?"""
	entries: list[CLovResourceEntry]

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		count = int.from_bytes(stream.read(4), "little")
		return cls(
			id=id,
			entries=[CLovResourceEntry.from_stream(stream) for _ in range(count)]
		)


@dataclass
class StringResource(SilverDBResource):
	"""Represents a string (Str, StrT, SCST, ACST) resource containing UTF-8 text within a SilverDB."""
	string: str

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		return cls(id=id, string=read_null_terminated_string(stream, encoding="utf-8"))

	def to_stream(self, stream: BinaryIO):
		stream.write(self.string.encode("utf-8"))
		stream.write(b"\x00")


class BitmapImageFormat(Enum):
	"""Formats available to SilverDB bitmaps (BMap)"""
	BGRA_8888 = 0x1888
	GREYSCALE_4 = 0x0004
	GREYSCALE_8 = 0x0008
	RGB_565 = 0x0565
	PALETTE_64 = 0x0064
	PALETTE_65 = 0x0065


_BITMAP_IMAGE_FORMAT_TO_FLAGS: dict[BitmapImageFormat, int] = {
	BitmapImageFormat.BGRA_8888: 0x0020,
	BitmapImageFormat.GREYSCALE_4: 0x0004,
	BitmapImageFormat.GREYSCALE_8: 0x0008,
	BitmapImageFormat.RGB_565: 0x0010,
	BitmapImageFormat.PALETTE_64: 0x0008,
	BitmapImageFormat.PALETTE_65: 0x0010
}


@dataclass
class BitmapResource(SilverDBResource):
	"""Represents a bitmap (BMap) or status-bar bitmap (STBm) resource within a SilverDB."""
	image_format: BitmapImageFormat
	image: PIL.Image.Image
	sub_id: int
	unk_0: int

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		image_format = BitmapImageFormat(int.from_bytes(stream.read(2), "little"))
		unk_0 = int.from_bytes(stream.read(2), "little")
		row_length = int.from_bytes(stream.read(2), "little")

		# we don't store this, because there seems to be a perfect mapping from image format to flags.
		flags = int.from_bytes(stream.read(2), "little")
		assert flags == _BITMAP_IMAGE_FORMAT_TO_FLAGS[image_format]

		# padding
		assert stream.read(8) == bytes(8)

		height = int.from_bytes(stream.read(4), "little")
		width = int.from_bytes(stream.read(4), "little")

		# sub_id seems to sometimes mirror the resource ID, and sometimes equal zero.
		sub_id = int.from_bytes(stream.read(4), "little")

		data_size = int.from_bytes(stream.read(4), "little")
		data_width = width

		greyscale = False
		pixels = []

		# actual parsing here:
		if image_format == BitmapImageFormat.BGRA_8888:
			# BGRA, big endian
			for _ in range((row_length // 4) * height):
				pixels.append(pixel_fromBGRA(stream))

		elif image_format == BitmapImageFormat.GREYSCALE_4:
			# 4-bit greyscale, might be inverted?
			greyscale = True
			data_width = row_length * 2
			for _ in range(row_length * height):
				data = stream.read(1)[0]
				pixels.append(17 * (data >> 4))
				pixels.append(17 * (data & 0b1111))

		elif image_format == BitmapImageFormat.GREYSCALE_8:
			# 8-bit greyscale, might be inverted?
			greyscale = True
			data_width = row_length
			for _ in range(row_length * height):
				pixels.append(stream.read(1)[0])

		elif image_format == BitmapImageFormat.RGB_565:
			# RGB565, not supported by Pillow
			data_width = row_length // 2
			pixels = pixels_from565(stream, (row_length // 2 * height) * 2)

		elif image_format == BitmapImageFormat.PALETTE_64:
			# hack: palette does not support BGRA so we can't use .raw
			palette_length = int.from_bytes(stream.read(4), "little")
			palette = []
			for _ in range(palette_length):
				palette.append(pixel_fromBGRA(stream))

			for _ in range(row_length * height):
				index = stream.read(1)[0]
				pixels.append(palette[index])

		elif image_format == BitmapImageFormat.PALETTE_65:
			palette_length = int.from_bytes(stream.read(4), "little")
			palette = []

			for _ in range(palette_length):
				palette.append(pixel_fromBGRA(stream))

			for _ in range((row_length // 2) * height):
				index = int.from_bytes(stream.read(2), "little")
				pixels.append(palette[index])
		else:
			raise NotImplementedError(f"{image_format=}")

		# parsing over, let's make a Pillow image!
		image = Image.new(
			mode="L" if greyscale else "RGBA",
			size=(data_width, height)
		)
		image.putdata(pixels)

		if data_width != width:
			image = image.crop((0, 0, width, height))

		return cls(id=id, unk_0=unk_0, sub_id=sub_id, image_format=image_format, image=image)

	def to_stream(self, stream: BinaryIO):
		image_format = self.image_format
		image = self.image
		width, height = image.size

		start_offset = stream.tell()  # we'll need this so we can seek back and calculate length.

		stream.write(int.to_bytes(image_format.value, 2, "little"))
		stream.write(int.to_bytes(self.unk_0, 2, "little"))

		flags = _BITMAP_IMAGE_FORMAT_TO_FLAGS[image_format]
		if image_format == BitmapImageFormat.BGRA_8888:
			# keep RGBA
			row_length = width * 4
		elif image_format == BitmapImageFormat.GREYSCALE_4:
			image = image.convert("L")
			row_length = math.ceil(image.size[0] / 2)  # will be used later
		elif image_format == BitmapImageFormat.GREYSCALE_8:
			image = image.convert("L")
			row_length = width
		elif image_format == BitmapImageFormat.RGB_565:
			image = image.convert("RGB")
			row_length = width * 2
		elif image_format == BitmapImageFormat.PALETTE_64:
			# keep RGBA
			row_length = width
		elif image_format == BitmapImageFormat.PALETTE_65:
			# keep RGBA
			row_length = width * 2
		else:
			raise ValueError(f"cannot pack unknown format {image_format:04x}")

		stream.write(int.to_bytes(row_length, 2, "little"))
		stream.write(int.to_bytes(flags, 2, "little"))
		stream.write(bytes(8))
		stream.write(int.to_bytes(height, 4, "little"))
		stream.write(int.to_bytes(width, 4, "little"))
		stream.write(int.to_bytes(self.sub_id, 4, "little"))

		# we'll seek back here to write length:
		length_offset = stream.tell()
		stream.write(bytes(4))

		if image_format == BitmapImageFormat.BGRA_8888:
			for pixel in image.getdata():
				stream.write(pixel_toBGRA(pixel))

		elif image_format == BitmapImageFormat.GREYSCALE_4:
			# this image will already be type L (8-bit greyscale) so we mostly just have to bitcrush it to 4 bits:

			pixels = list(image.getdata())

			array = bytearray()

			for y in range(height):
				row = pixels[(y * width):((y * width) + width)]

				if len(row) % 2 != 0:
					row.append(0)

				for x_idx in range(0, len(row), 2):
					i0, i1 = row[x_idx:x_idx + 2]
					array.append(((i0 // 17) << 4) + (i1 // 17))
			stream.write(array)

		elif image_format == BitmapImageFormat.GREYSCALE_8:
			# this image will already be type L, so the data is already in the right format.
			stream.write(bytes(image.getdata()))

		elif image_format == BitmapImageFormat.RGB_565:
			for pixel in image.getdata():
				stream.write(int.to_bytes(pixel_to565(pixel), 2, "little"))

		elif image_format in {BitmapImageFormat.PALETTE_64, BitmapImageFormat.PALETTE_65}:
			pixels = image.getdata()
			unique_pixels = list(sorted(set(pixels)))  # here's our palette!

			if image_format == BitmapImageFormat.PALETTE_64:
				if len(unique_pixels) > 0xFF:
					raise ValueError(f"more than 255 colors in {self.id}")

			elif image_format == BitmapImageFormat.PALETTE_65:
				if len(unique_pixels) > 0xFFFF:
					raise ValueError(f"more than 65535 colors in {self.id}")

			stream.write(int.to_bytes(len(unique_pixels), 4, "little"))

			for color in unique_pixels:
				stream.write(pixel_toBGRA(color))

			reverse_index = {color: n for n, color in enumerate(unique_pixels)}

			for pixel in pixels:
				stream.write(int.to_bytes(
					reverse_index[pixel],
					length=1 if image_format == BitmapImageFormat.PALETTE_64 else 2,
					byteorder="little"
				))
		else:
			raise ValueError(f"unknown format: {image_format}")

		# wheeeww. now we get to seek back and write our length value
		end_offset = stream.tell()
		length = (end_offset - start_offset)
		stream.seek(length_offset)
		stream.write(int.to_bytes((length - 32), 4, "little"))  # subtract the 32-byte head
		stream.seek(end_offset)


@dataclass
class UsagesResourceEntry:
	"""Represents an entry within a SilverDB usages (SUse) resource."""

	layout_id_0: int  # both these IDs exist in VLyt and TEVT
	layout_id_1: int
	vcvs_id: int  # exists in VCvs
	tmap_id: Optional[int]
	idk_id: Optional[int]

	# i don't know for sure what these do...
	# setting them all to False seems to do nothing
	# but making them all True crashes retailOS.
	unk_1: bool
	unk_2: bool
	unk_3: bool

	def to_stream(self, stream: BinaryIO):
		start_offset = stream.tell()
		stream.write(bytes(4))
		stream.write(b"SUse"[::-1])
		o1 = stream.tell()
		stream.write(b"\xFE\xFF\xFF\x7F" * 4)
		stream.write((self.tmap_id or 0).to_bytes(4, "little"))
		stream.write(self.layout_id_0.to_bytes(4, "little"))
		stream.write((self.idk_id or 0).to_bytes(4, "little"))
		stream.write(self.layout_id_1.to_bytes(4, "little"))

		stream.write((2 * self.unk_1).to_bytes(4, "little"))
		stream.write(bytes(8))
		stream.write(bytes(1))
		stream.write((2 * self.unk_2).to_bytes(3, "little"))
		stream.write(self.vcvs_id.to_bytes(4, "little"))
		stream.write(bytes(1))
		stream.write(self.unk_3.to_bytes(3, "little"))
		stream.write(bytes(8))
		stream.write((1).to_bytes(4, "little"))
		o2 = stream.tell()

		length = o2 - o1
		stream.seek(start_offset)
		stream.write(length.to_bytes(4, "little"))
		stream.seek(o2)

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		length_value = int.from_bytes(stream.read(4), "little")
		assert stream.read(4)[::-1] == b"SUse"

		o1 = stream.tell()

		crap = stream.read(16)
		if crap != b"\xFE\xFF\xFF\x7F" * 4:
			# hmm, sometimes this stuff looks different, but it doesnt seem to matter?
			# print(f"unk data: {stuff.hex(' ')}")
			pass

		tmap_id = int.from_bytes(stream.read(4), "little")  # can be 0
		layout_id_0 = int.from_bytes(stream.read(4), "little")
		idk_id = int.from_bytes(stream.read(4), "little")
		layout_id_1 = int.from_bytes(stream.read(4), "little")

		unk_1 = int.from_bytes(stream.read(1), "little")  # either 0 or 2
		assert unk_1 in {0, 2}
		unk_1 = bool(unk_1)
		assert int.from_bytes(stream.read(3), "little") == 2

		assert stream.read(8) == bytes(8)
		assert stream.read(1) == bytes(1)

		unk_2 = int.from_bytes(stream.read(3), "little")  # either 0 (usually) or 2 (sometimes)
		assert unk_2 in {0, 2}
		unk_2 = bool(unk_2)

		vcvs_id = int.from_bytes(stream.read(4), "little")

		assert stream.read(1) == bytes(1)
		unk_3 = int.from_bytes(stream.read(3), "little")  # either 0 (usually) or 1 (very rarely)
		assert unk_3 in {0, 1}
		unk_3 = bool(unk_3)

		assert stream.read(8) == bytes(8)
		assert int.from_bytes(stream.read(4), "little") == 1

		o2 = stream.tell()
		assert o2 - o1 == length_value
		return cls(
			tmap_id=tmap_id or None,
			layout_id_0=layout_id_0,
			layout_id_1=layout_id_1,
			idk_id=idk_id or None,
			unk_1=unk_1,
			unk_2=unk_2,
			vcvs_id=vcvs_id,
			unk_3=unk_3
		)


@dataclass
class UsagesResource(SilverDBResource):
	"""Represents a usages (SUse) resource within a SilverDB."""

	entries: list[UsagesResourceEntry]

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		count = int.from_bytes(stream.read(4), "little")
		return cls(id=id, entries=[UsagesResourceEntry.from_stream(stream) for _ in range(count)])

	def to_stream(self, stream: BinaryIO):
		stream.write(len(self.entries).to_bytes(4, "little"))
		for entry in self.entries:
			entry.to_stream(stream)


@dataclass
class ViewResourceEntry:
	"""Represents an entry within a SilverDB View resource."""

	id: int

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		body_length = int.from_bytes(stream.read(4), "little")
		id = int.from_bytes(stream.read(4), "little")
		body_start = stream.tell()

		unk_0 = int.from_bytes(stream.read(4), "little")
		print(f"{unk_0=}")
		id_1 = int.from_bytes(stream.read(4), "little")

		unks_0 = []
		for _ in range(17):
			unks_0.append(int.from_bytes(stream.read(4), "little"))

		entry_type = stream.read(4)[::-1].decode("ascii")

		unky_0 = int.from_bytes(stream.read(4), "little")
		unky_1 = int.from_bytes(stream.read(4), "little")
		id_2 = int.from_bytes(stream.read(4), "little")
		id_3 = int.from_bytes(stream.read(4), "little")
		unky_2 = int.from_bytes(stream.read(4), "little")
		unky_3 = int.from_bytes(stream.read(4), "little")
		unky_4 = bool.from_bytes(stream.read(4))
		unky_5 = int.from_bytes(stream.read(4), "little")
		unky_6 = int.from_bytes(stream.read(4), "little")
		unky_7 = bool.from_bytes(stream.read(4))
		unky_8 = int.from_bytes(stream.read(4), "little")
		unky_9 = int.from_bytes(stream.read(4), "little")
		assert stream.read(8) == bytes(8)
		assert int.from_bytes(stream.read(4), "little") == 16712193
		assert stream.read(4) == bytes(4)

		id_4 = int.from_bytes(stream.read(4), "little")
		id_5 = int.from_bytes(stream.read(4), "little")
		print(f"{body_length - (stream.tell() - body_start)}")
		stream.seek(body_start + body_length)

		print(f"{id=} {entry_type=} {id_5=}")

		return cls(id=id)


@dataclass
class ViewResource(SilverDBResource):
	"""Represents a view (View) resource within a SilverDB."""
	entries: list[ViewResourceEntry]

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		count = int.from_bytes(stream.read(4), "little")
		return cls(id=id, entries=[ViewResourceEntry.from_stream(stream) for _ in range(count)])


@dataclass
class SourcesResourceEntry:
	"""Represents an entry within a SilverDB sources (SORC) resource."""
	id_0: int
	unk_0: int
	unk_1: int

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		length = int.from_bytes(stream.read(4), "little")
		assert length == 12
		assert stream.read(4)[::-1] == b"SORC"

		unk_0 = int.from_bytes(stream.read(4), "little")
		id_0 = int.from_bytes(stream.read(4), "little")
		unk_1 = int.from_bytes(stream.read(4), "little")  # either 1 or 8, prob a bitfield

		return cls(unk_0=unk_0, id_0=id_0, unk_1=unk_1)

	def to_stream(self, stream: BinaryIO):
		stream.write((12).to_bytes(4, "little"))
		stream.write(b"SORC"[::-1])
		stream.write(self.unk_0.to_bytes(4, "little"))
		stream.write(self.id_0.to_bytes(4, "little"))
		stream.write(self.unk_1.to_bytes(4, "little"))


@dataclass
class SourcesResource(SilverDBResource):
	"""Represents a sources (SORC) resource within a SilverDB."""
	entries: list[SourcesResourceEntry]

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		count = int.from_bytes(stream.read(4), "little")
		return cls(id=id, entries=[SourcesResourceEntry.from_stream(stream) for _ in range(count)])

	def to_stream(self, stream: BinaryIO):
		stream.write(len(self.entries).to_bytes(4, "little"))
		for entry in self.entries:
			entry.to_stream(stream)


class SliceParameters(NamedTuple):
	"""Represents an image's corresponding 9-slice parameters,
	defined by offsets from the top, bottom, left, and right sides, in pixel space."""
	left: int
	right: int
	top: int
	bottom: int


@dataclass
class DecorationResource(SilverDBResource):
	"""Represents a decoration (DECO) resource within a SilverDB.
	This resource contains 9-slice data for an image, and is used for certain rounded corners in the UI."""
	image_id_0: int
	image_id_1: Optional[int]
	slice: SliceParameters

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		id_0, id_1, id_again, left, right, top, bottom = (int.from_bytes(stream.read(4), "little") for _ in range(7))
		assert id_again == id
		return cls(
			id=id,
			image_id_0=id_0,
			image_id_1=id_1 or None,
			slice=SliceParameters(left, right, top, bottom)
		)

	def to_stream(self, stream: BinaryIO):
		for value in (self.image_id_0, self.image_id_1 or 0, self.id, *self.slice):
			stream.write(value.to_bytes(4, "little"))


@dataclass
class RawResource(SilverDBResource):
	"""Type used for all unparseable SilverDB resources."""
	data: bytes

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		return cls(id=id, data=stream.read(length))

	def to_stream(self, stream: BinaryIO):
		stream.write(self.data)

	def __repr__(self):
		return f"<RawResource id={self.id} len(data)={len(self.data)}>"


@dataclass
class LocalizedDateTimeResource(SilverDBResource):
	"""Represents a localized date-time (LDTm) resource within a SilverDB."""

	referenced_ids: list[int]  # a list of IDs referencing string resources
	unk_0: int

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		return cls(
			id=id,
			referenced_ids=[
				int.from_bytes(stream.read(4), "little")
				for _ in range(length // 4)
			],
			unk_0=int.from_bytes(stream.read(2), "little")
		)

	def to_stream(self, stream: BinaryIO):
		for referenced_id in self.referenced_ids:
			stream.write(referenced_id.to_bytes(4, "little"))

		stream.write(self.unk_0.to_bytes(2, "little"))


class FontResourceStyle(Enum):
	HELVETICA = 0
	HELVETICA_BOLD = 1
	IPOD_SYMBOLS = 2


@dataclass
class FontResource(SilverDBResource):
	"""Represents a font (FONT) resource within a SilverDB."""

	font_name_string_id: int  # ID of a string containing the name of the font
	font_size: int  # seems to be in pixels
	font_style: FontResourceStyle

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		return cls(
			id=id,
			font_name_string_id=int.from_bytes(stream.read(4), "little"),
			font_size=int.from_bytes(stream.read(4), "little"),
			font_style=FontResourceStyle(int.from_bytes(stream.read(1)))
		)

	def to_stream(self, stream: BinaryIO):
		stream.write(self.font_name_string_id.to_bytes(4, "little"))
		stream.write(self.font_size.to_bytes(4, "little"))
		stream.write(self.font_style.value.to_bytes(1))


@dataclass
class SpeakableStringResource(SilverDBResource):
	"""Represents a speakable string (SStr) resource within a SilverDB."""
	speakable_id: bytes  # turn this to hex and you will find a file with this name in /Resources/Speakable/UISS0000/

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		identifier = stream.read(8)[::-1]
		assert stream.read(4)[::-1] == b"UISS"
		assert stream.read(4) == b"\x00\x00\xB1\xDB"
		return cls(id=id, speakable_id=identifier)

	def to_stream(self, stream: BinaryIO):
		stream.write(self.speakable_id[::-1])
		stream.write(b"UISS"[::-1])
		stream.write(b"\x00\x00\xB1\xDB")

	def __repr__(self):
		return f"<{self.__class__.__name__} id={self.id}; Speakable ID: {self.speakable_id.hex().upper()}>"


@dataclass
class AnimationEntryT3DP:
	"""Represents a T3DP animation entry(?) within a SilverDB ANIM resource."""
	unk_2: int
	unk_3: int
	unk_4: int
	floats: list[float]

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		assert int.from_bytes(stream.read(4), "little") == 3600000
		assert int.from_bytes(stream.read(4), "little") == 3600000
		unk_2 = int.from_bytes(stream.read(4), "little")

		floats = []
		for _ in range(6):
			assert stream.read(8) == bytes(8)
			float_val, = struct.unpack("f", stream.read(4))
			floats.append(float_val)

		unk_3 = int.from_bytes(stream.read(4), "little")
		unk_4 = int.from_bytes(stream.read(4), "little")

		return cls(unk_2, unk_3, unk_4, floats)

	def to_stream(self, stream: BinaryIO):
		stream.write((3600000).to_bytes(4, "little"))
		stream.write((3600000).to_bytes(4, "little"))
		stream.write(self.unk_2.to_bytes(4, "little"))
		for float_val in self.floats:
			stream.write(bytes(8))
			stream.write(struct.pack("f", float_val))
		stream.write(self.unk_3.to_bytes(4, "little"))
		stream.write(self.unk_4.to_bytes(4, "little"))


@dataclass
class AnimationEntryRaw:
	"""Represents any unparseable entry within a SilverDB ANIM resource."""
	type: str
	data: bytes

	def __repr__(self):
		return f"<{self.__class__.__name__} type={self.type} len(data)={len(self.data)}>"


@dataclass
class AnimationResource(SilverDBResource):
	"""Represents an animation (ANIM) resource within a SilverDB."""
	entries: list

	@classmethod
	def from_stream(cls, id: int, stream: BinaryIO, length: int):
		count = int.from_bytes(stream.read(4), "little")
		entries = []

		for _ in range(count):
			length = int.from_bytes(stream.read(4), "little")
			magic = stream.read(4)[::-1]
			assert magic == b"ANIM"
			offset = stream.tell()

			type = stream.read(4)[::-1].decode("ascii")
			if type == "T3DP":
				entries.append(AnimationEntryT3DP.from_stream(stream))
			else:
				entries.append(AnimationEntryRaw(type=type, data=stream.read(length - 4)))
			stream.seek(offset + length)

		return cls(id=id, entries=entries)

	def to_stream(self, stream: BinaryIO):
		stream.write(len(self.entries).to_bytes(4, "little"))

		for entry in self.entries:
			start_offset = stream.tell()
			stream.write(bytes(4))
			stream.write(b"ANIM")
			data_start_offset = stream.tell()

			if isinstance(entry, AnimationEntryRaw):
				stream.write(entry.type.encode("ascii")[::-1])
				stream.write(entry.data)
			elif isinstance(entry, AnimationEntryT3DP):
				entry.to_stream(stream)

			end_offset = stream.tell()
			length = end_offset - data_start_offset
			stream.seek(start_offset)
			stream.write(length.to_bytes(4, "little"))
			stream.seek(end_offset)


"""Maps section names to SilverDBResource types."""
_SECTION_TO_RESOURCE_TYPE: dict[str, Type[SilverDBResource]] = {
	# "View": ViewResource,
	# "CLov": CLovResource,
	"COLR": ColorResource,
	"Str ": StringResource,
	"StrT": StringResource,
	"SCST": StringResource,
	"ACST": StringResource,
	"SUse": UsagesResource,
	"SStr": SpeakableStringResource,
	"SORC": SourcesResource,
	"BMap": BitmapResource,
	"StBM": BitmapResource,
	"LDTm": LocalizedDateTimeResource,
	"FONT": FontResource,
	"ANIM": AnimationResource,
	"DECO": DecorationResource
}

"""Maps section names to their jumpiness (apparently whether IDs are incremental). Seems to be constant for each type."""
_SECTION_IS_JUMPY = {
	"AALI": True,
	"ACST": True,
	"AEVT": False,
	"ANIM": True,
	"BMap": True,
	"CEVT": True,
	"CLov": False,
	"COLR": True,
	"CSov": False,
	"DECO": True,
	"FONT": True,
	"LDTm": True,
	"MASt": True,
	"PVCM": True,
	"SANI": True,
	"SCRN": True,
	"SCST": True,
	"SEVT": True,
	"SLst": True,
	"SORC": True,
	"SRVL": True,
	"SStr": True,
	"SUse": False,
	"StBM": False,
	"Str ": False,
	"StrT": True,
	"T10N": True,
	"TEVT": True,
	"TMLT": False,
	"TMap": True,
	"TVCL": True,
	"TVCS": True,
	"VCvs": False,
	"VLyt": False,
	"VSlt": False,
	"View": True
}


@dataclass
class SilverDBSection:
	"""Represents a section within a SilverDB."""
	type: str
	resources: list[SilverDBResource]

	def __repr__(self):
		return f"<{self.__class__.__name__} type={self.type!r} len(resources)={len(self.resources)}>"


@dataclass
class SilverDB:
	"""Represents an iPod SilverDB, used to store resources, layouts, and bitmaps for the iPod UI."""
	sections: list[SilverDBSection]

	def get_section(self, section_type: str) -> SilverDBSection:
		"""Get a section with the specified section type."""

		try:
			return next(iter(section for section in self.sections if section.type == section_type))
		except StopIteration:
			raise ValueError(f"SilverDB does not contain section {section_type!r}")

	@classmethod
	def from_stream(cls, stream: BinaryIO):
		"""Parse a SilverDB from the given stream."""
		start = stream.tell()

		version = int.from_bytes(stream.read(4), "little")
		assert version == 3

		header_length = int.from_bytes(stream.read(4), "little")
		section_count = int.from_bytes(stream.read(4), "little")

		# parse all the section headers
		section_headers: list[_SilverDBSectionHeader] = []
		for i in range(section_count):
			section_headers.append(_SilverDBSectionHeader.from_stream(stream))

		# parse all the resource headers
		sections_resource_headers: dict[str, tuple[_SilverDBResourceHeader, ...]] = {}
		for section_header in section_headers:
			if section_header.type in sections_resource_headers:
				raise ValueError("duplicate table")
			assert section_header.jumpy == _SECTION_IS_JUMPY[section_header.type]
			stream.seek(start + section_header.offset)
			sections_resource_headers[section_header.type] = tuple((
				_SilverDBResourceHeader.from_stream(stream)
				for _ in range(section_header.resource_count)
			))

		# sanity check: make sure we're in the right place
		misalignment = header_length - (stream.tell() - start)
		if misalignment > 4:
			# some SilverDBs seem to pad this offset out with some null bytes, which means misalignment=4
			raise ValueError("parse error")

		# now create the final sections
		sections = []
		for section_type, resource_headers in sections_resource_headers.items():
			section_resource_class = _SECTION_TO_RESOURCE_TYPE.get(section_type, RawResource)

			resources = []
			for resource_header in resource_headers:
				stream.seek(start + header_length + resource_header.offset)  # seek to the resource
				resources.append(section_resource_class.from_stream(
					id=resource_header.id,
					stream=stream,
					length=resource_header.length
				))

			sections.append(SilverDBSection(
				type=section_type,
				resources=resources
			))

		# all done :3
		return cls(sections=sections)

	def to_stream(self, stream: BinaryIO):
		"""Save the SilverDB to the given stream."""
		section_headers_length = (4 * 4 * len(self.sections))
		resource_headers_length = (4 * 3 * sum(len(section.resources) for section in self.sections))

		header_length = (section_headers_length + resource_headers_length) + 12

		start = stream.tell()
		stream.write((3).to_bytes(4, "little"))
		stream.write(header_length.to_bytes(4, "little"))
		stream.write(len(self.sections).to_bytes(4, "little"))
		stream.seek(start + header_length)

		section_headers: dict[str, _SilverDBSectionHeader] = {}
		section_resource_headers: dict[str, list[_SilverDBResourceHeader]] = {}

		# write all resources, creating the section and resource headers
		for _, section in enumerate(self.sections):
			section_header = _SilverDBSectionHeader(
				type=section.type,
				resource_count=len(section.resources),
				jumpy=_SECTION_IS_JUMPY[section.type],
				offset=-1
			)
			section_headers[section.type] = section_header

			resource_headers = []
			for _, resource in enumerate(section.resources):
				# write the resource:
				resource_offset = stream.tell()
				resource.to_stream(stream)  # <- write it
				resource_end_offset = stream.tell()
				resource_length = resource_end_offset - resource_offset

				resource_headers.append(_SilverDBResourceHeader(
					id=resource.id,
					offset=resource_offset - start - header_length,
					length=resource_length
				))

				# pad to 4 bytes:
				misalignment = (stream.tell() - start) % 4
				if misalignment > 0:
					stream.write(bytes(4 - misalignment))

			section_resource_headers[section.type] = resource_headers

		end_offset = stream.tell()

		# seek back to write all resource headers, and update section headers with the offsets
		stream.seek(start + 12 + section_headers_length)
		for section_type, resource_headers in section_resource_headers.items():
			section_resource_headers_start = stream.tell()
			section_header = section_headers[section_type]
			section_header.offset = section_resource_headers_start - start

			for resource_header in resource_headers:
				resource_header.to_stream(stream)

		# finally, seek to the start to write all the section headers
		stream.seek(start + 12)
		for section_header in section_headers.values():
			section_header.to_stream(stream)

		# go back to the end
		stream.seek(end_offset)
		# all done :3
