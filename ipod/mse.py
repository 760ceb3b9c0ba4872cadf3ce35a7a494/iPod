"""
implementation of the MSE file format, used to store a list of IMG1 firmware partitions.
"""

from dataclasses import dataclass
from typing import BinaryIO

OFFSET = 0x5000  # fixme, this is different between devices!


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


def read_mse_header(stream: BinaryIO) -> list[ImageMetadata]:
	stream.seek(OFFSET)

	images = []
	for image_index in range(16):
		# 16 slots
		image_data = stream.read(40)
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


def read_mse_image(stream: BinaryIO, image: ImageMetadata) -> bytes:
	stream.seek(image.dev_offset + 0x1000)  # 4096 padding? unclear.
	read_length = image.length + 0x800  # length does not include the 0x800 img1 header overhead
	return stream.read(read_length)
