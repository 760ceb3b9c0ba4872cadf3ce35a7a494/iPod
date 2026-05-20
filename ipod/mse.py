"""
implementation of the MSE file format, used to store a list of IMG1 firmware partitions.
"""

from dataclasses import dataclass
from typing import BinaryIO

OFFSET = 0x5000  # fixme, this is different between devices!
STOP_SIGN = rb"{{~~  /-----\   " \
			rb"{{~~ /       \  " \
			rb"{{~~|         | " \
			rb"{{~~| S T O P | " \
			rb"{{~~|         | " \
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

MAGIC_0 = b"\x5D\x69\x68\x5B\x00\x40\x00\x00\x0C\x01\x03\x00"


@dataclass
class ImageMetadata:
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
	offset = stream.tell()
	stream.seek(len(STOP_SIGN))
	result = stream.read(len(MAGIC_0)) == MAGIC_0
	stream.seek(offset)
	return result


class MSEFile:
	def __init__(self, stream: BinaryIO):
		if not looks_like_mse(stream):
			raise ValueError("doesn't look like an MSE file to me!")
		self._stream = stream
		self.images = self._list_images()

	def read_image_contents(self, image: ImageMetadata):
		self._stream.seek(image.dev_offset + 0x1000)  # 4096 padding? unclear.
		read_length = image.length + 0x800  # length does not include the 0x800 img1 header overhead
		return self._stream.read(read_length)

	def _list_images(self) -> list[ImageMetadata]:
		self._stream.seek(OFFSET)

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
