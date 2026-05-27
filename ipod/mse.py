"""
implementation of the MSE file format, used to store a list of IMG1 firmware partitions.
"""

from dataclasses import dataclass
from typing import BinaryIO

_OFFSET = 0x5000  # fixme, this is different between devices!
_STOP_SIGN = rb"{{~~  /-----\   " \
			 rb"{{~~ /       \  " \
			 rb"{{~~|         | " \
			 rb"{{~~| S T O P | " \
			 rb"{{~~ \       /  " \
			 rb"{{~~  \-----/   " \
			 rb"Copyright(C) 200" \
			 rb"1 Apple Computer" \
			 rb", Inc.----------" \
		 	 rb"----------------" \
			 rb"----------------" \
			 rb"----------------" \
			 rb"----------------" \
			 rb"----------------" \
			 rb"---------------" b"\x00"

_MAGIC_0 = b"\x5D\x69\x68\x5B\x00\x40\x00\x00\x0C\x01\x03\x00"


@dataclass
class ImageMetadata:
	"""Metadata referencing an IMG1 file contained within this MSE"""
	target: str  # "NAND", "NOR!", "flsh"
	name: str  # "disk", "diag", "appl", "lbat", "bdsw", "chrg", "rsrc", "osos"

	# id: int
	dev_offset: int
	length: int
	address: int

	entry_offset: int
	# checksum: int
	version: int
	load_address: int


def looks_like_mse(stream: BinaryIO):
	"""Determine if a given stream looks like it contains MSE data."""
	offset = stream.tell()
	stream.seek(len(_STOP_SIGN))
	result = stream.read(len(_MAGIC_0)) == _MAGIC_0
	stream.seek(offset)
	return result


class MSEFile:
	"""Represents an MSE file."""
	def __init__(self, stream: BinaryIO):
		if not looks_like_mse(stream):
			raise ValueError("doesn't look like an MSE file to me!")
		self._stream = stream
		self.images: list[ImageMetadata] = self._list_images()
		"""A list of images contained within this MSE file"""

	def read_image_contents(self, image: ImageMetadata) -> bytes:
		"""Read the IMG1 contents of an image contained within this MSE file."""
		self._stream.seek(image.dev_offset + 0x1000)  # 4096 padding? unclear.
		read_length = image.length + 0x800  # length does not include the 0x800 img1 header overhead
		return self._stream.read(read_length)

	def _list_images(self) -> list[ImageMetadata]:
		self._stream.seek(_OFFSET)

		images = []
		for image_index in range(16):
			# 16 slots
			image_data = self._stream.read(40)
			if image_data[0:4] == b"\x00\x00\x00\x00":
				# placeholder
				continue

			pieces = [image_data[i:i + 4] for i in range(0, 40, 4)]

			image_target = pieces[0][::-1].decode("ascii")
			image_name = pieces[1][::-1].decode("ascii")

			image = ImageMetadata(
				target=image_target,
				name=image_name,
				# id=int.from_bytes(pieces[2], "little"),
				dev_offset=int.from_bytes(pieces[3], "little"),
				length=int.from_bytes(pieces[4], "little"),
				address=int.from_bytes(pieces[5], "little"),
				entry_offset=int.from_bytes(pieces[6], "little"),
				# checksum=int.from_bytes(pieces[7], "little"),
				version=int.from_bytes(pieces[8], "little"),
				load_address=int.from_bytes(pieces[9], "little"),
			)

			images.append(image)
		return images
