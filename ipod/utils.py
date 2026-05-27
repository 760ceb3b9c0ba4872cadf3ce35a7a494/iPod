"""
various utilities
"""
import plistlib
import subprocess
from typing import BinaryIO


def buffered_copy(
		source: BinaryIO,
		destination: BinaryIO,
		*,
		limit: int = None,
		buffer_size: int = 0x1000
):
	offset = 0

	while True:
		read_amount = min(buffer_size, limit - offset) if limit else buffer_size
		buffer = source.read(read_amount)
		offset += read_amount

		destination.write(buffer)

		if len(buffer) < buffer_size:
			# either we've hit the limit or there is no more data
			break


def buffered(
		source: BinaryIO,
		*,
		limit: int = None,
		buffer_size: int = 0x1000
):
	offset = 0

	while True:
		read_amount = min(buffer_size, limit - offset) if limit else buffer_size
		buffer = source.read(read_amount)
		offset += read_amount

		yield buffer

		if len(buffer) < buffer_size:
			# either we've hit the limit or there is no more data
			break


# noinspection PyPep8Naming
def macOS_get_mount_point(serial_number: str):
	"""Get the mount point of a USB device (like /Volumes/iPod) given its unique serial"""
	process = subprocess.run(
		args=[
			"/usr/sbin/system_profiler",
			"-nospawn", "-xml",
			"SPUSBDataType",
			"-detailLevel", "full"
		],
		stdout=subprocess.PIPE
	)
	process.check_returncode()
	plist_data = process.stdout
	start_data = plistlib.loads(plist_data)[0]

	def find_device_data_within(data: dict) -> dict | None:
		# data has a key _items containing a list of either items or other dicts with the key _items.
		for sub_data in data["_items"]:
			if "_items" in sub_data:
				found_data = find_device_data_within(sub_data)
				if found_data:
					return found_data
			elif "serial_num" in sub_data:
				# the libusb address and macOS location id seem to differ after the device is reattached.
				# so i went with checking s/n instead.
				if serial_number == sub_data["serial_num"]:
					# YAY WE FOUND IT ^w^
					return sub_data

		return None

	# recursively find the device
	this_device_data = find_device_data_within(start_data)
	if this_device_data is None:
		# noo .. we didnt find it ... T_T
		return None

	media_data = this_device_data.get("Media")
	if media_data is None:
		# this device is attached but not mounted rn.
		return None

	if "volumes" not in media_data[0]:
		return None

	for volume in media_data[0]["volumes"]:
		if "mount_point" in volume:
			return volume["mount_point"]

	return None


def numeric_build_id_to_string(build_id: int):
	"""Convert a numeric build ID to a string"""
	return f"{build_id >> 24 & 0b1111}.{build_id >> 20 & 0b1111}.{build_id >> 16 & 0b1111}"
