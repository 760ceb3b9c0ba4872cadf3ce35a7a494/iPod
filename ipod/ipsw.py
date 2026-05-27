"""
Implementation of the iPod Software (IPSW) file format, used to store iPod firmware images.
only the subset of IPSW files containing iPod firmware are implemented
"""
import io
import plistlib
import typing
from dataclasses import dataclass
from enum import Enum
from os import PathLike
from pathlib import PurePosixPath
from typing import BinaryIO, IO, Optional
from zipfile import ZipFile

from ipod.definitions import iPodTarget, USB_PID_INDEX, UPDATER_FAMILY_ID_INDEX


class IPSWKind(Enum):
	"""Enumerates the kinds of IPSW files."""
	PAYLOAD = "payload"
	"""IPSW containing an actual firmware payload, used to update an iPod."""
	RECOVERY = "recovery"
	"""IPSW containing a recovery IMG1 to send to an iPod in DFU or WTF mode."""


def _product_type_id_to_usb_pid(product_type_id: int) -> tuple[int, int]:
	return (product_type_id >> 0x10) & 0xFFFF, product_type_id & 0x10


def _get_ipsw_kind(zipfile: ZipFile):
	name_list = zipfile.namelist()
	if "manifest.plist" in name_list:
		return IPSWKind.PAYLOAD
	elif "Restore.plist" in name_list:
		return IPSWKind.RECOVERY
	else:
		raise ValueError("invalid or unknown IPSW")


def get_ipsw_kind(file: str | PathLike | BinaryIO) -> IPSWKind:
	"""Determine the kind of an IPSW file."""
	with ZipFile(
			file=file,
			mode="r",
			allowZip64=False,
	) as zipfile:
		return _get_ipsw_kind(zipfile)


class _IPSWFile:
	def __init__(self, file: str | PathLike | BinaryIO):
		self._zipfile = ZipFile(
			file=file,
			mode="r",
			allowZip64=False,
		)
		if self._zipfile.testzip() is not None:
			raise ValueError("failed test, IPSW zipfile may be corrupt.")

		self._namelist = self._zipfile.namelist()

	def __enter__(self):
		self._zipfile.__enter__()
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self._zipfile.__exit__(exc_type, exc_val, exc_tb)


class RecoveryIPSWType(Enum):
	"""Enumerates the types of IMG1 files that can be stored in recovery IPSWs."""
	FIRMWARE = "firmware"
	"""IPSWs containing second-state bootloaders to send to devices in DFU mode."""
	WTF = "wtf"
	"""IPSWs containing a 'forced disk mode' recovery image."""


@dataclass
class RecoveryIPSWManifest:
	"""Manifest of a recovery IPSW file"""
	firmware_directory: str
	product_build_version: str
	supported_product_type_ids: dict[str, list[int]]


class RecoveryIPSWFile(_IPSWFile):
	"""Represents a recovery IPSW file."""
	def __init__(self, file: str | PathLike | BinaryIO):
		super().__init__(file)
		if _get_ipsw_kind(self._zipfile) != IPSWKind.RECOVERY:
			raise ValueError("must be a recovery IPSW")

	def _get_img1_file_path(self) -> str:
		manifest = self.get_manifest()
		for name in self._namelist:
			if name.startswith(f"{manifest.firmware_directory}/") and name.endswith(".dfu"):
				return name
		raise ValueError("failed to find img1 file")

	def get_img1_type(self) -> RecoveryIPSWType:
		"""Return the type of the IMG1 stored within this recovery IPSW."""
		start_part = self.get_img1_filename().split(".")[0]
		return RecoveryIPSWType[start_part]  # seems to work fine idc

	def get_img1_filename(self) -> str:
		"""Return the filename of the IMG1 stored within this recovery IPSW."""
		pure_path = PurePosixPath(self._get_img1_file_path())
		return pure_path.name

	def get_img1_data(self) -> bytes:
		"""Return the data of the IMG1 stored within this recovery IPSW."""
		return self._zipfile.read(self._get_img1_file_path())

	def get_img1_length(self) -> int:
		"""Return the length of the IMG1 data stored within this recovery IPSW."""
		return self._zipfile.getinfo(self._get_img1_file_path()).file_size

	def open_img1_file(self) -> typing.IO[bytes]:
		"""Open the IMG1 file stored within this recover IPSW."""
		return self._zipfile.open(self._get_img1_file_path())

	def get_manifest(self) -> RecoveryIPSWManifest:
		"""Return the manifest of this recovery IPSW."""
		raw_data = self._zipfile.read("Restore.plist")
		plist_data = plistlib.loads(raw_data)
		return RecoveryIPSWManifest(
			firmware_directory=plist_data["FirmwareDirectory"],
			product_build_version=plist_data["ProductBuildVersion"],
			supported_product_type_ids=plist_data["SupportedProductTypeIDs"]
		)

	def get_target_device_usb_pids(self) -> list[int]:
		"""Get the USB product IDs targeted by this recovery IPSW."""
		manifest = self.get_manifest()
		type_ids = manifest.supported_product_type_ids["DFU"]

		return [_product_type_id_to_usb_pid(type_id)[0] for type_id in type_ids]

	def get_target_devices(self) -> list[iPodTarget]:
		"""Get the iPodTargets targeted by this recovery IPSW."""
		return [USB_PID_INDEX[pid] for pid in self.get_target_device_usb_pids()]

	def is_compatible_with(self, target: iPodTarget) -> bool:
		"""Determine if this IPSW is compatible with a target."""
		for our_target in self.get_target_devices():
			if our_target.is_compatible_with(target):
				return True
		return False


@dataclass()
class PayloadIPSWManifest:
	"""Manifest of a payload IPSW file"""
	firmware_name: str
	"""Name of the firmware payload file contained in this IPSW"""
	bootloader_name: str
	"""Name of the bootloader IMG1 file contained in this IPSW"""
	updater_family_id: int
	"""Updater family ID targeted by this IPSW"""
	family_id: int
	"""Family ID(?) targeted by this IPSW"""
	build_id: Optional[int] = None
	"""Internal build ID of this IPSW"""
	visible_build_id: Optional[int] = None
	"""User-facing build ID of this IPSW"""
	build_version: Optional[str] = None
	"""Build version of this IPSW"""
	product_version: Optional[str] = None
	"""User-facing product version of this IPSW"""

	def get_target_device(self):
		"""Return the iPodTarget applicable to this IPSW manifest"""
		return UPDATER_FAMILY_ID_INDEX[self.updater_family_id]

	def is_compatible_with(self, target: iPodTarget):
		"""Determine if this IPSW manifest is compatible with the given target"""
		return self.get_target_device().is_compatible_with(target)


class PayloadIPSWFile(_IPSWFile):
	"""Represents a payload IPSW file"""
	def __init__(self, file: str | PathLike | BinaryIO):
		super().__init__(file)
		if _get_ipsw_kind(self._zipfile) != IPSWKind.PAYLOAD:
			raise ValueError("must be a payload IPSW")

	def get_manifest(self) -> PayloadIPSWManifest:
		"""Return the manifest of this IPSW"""
		raw_data = self._zipfile.read("manifest.plist")
		plist_data = plistlib.loads(raw_data)["FirmwarePayload"]
		return PayloadIPSWManifest(
			firmware_name=plist_data["FirmwareName"],
			bootloader_name=plist_data.get("BootloaderName"),

			# older fw
			build_id=plist_data.get("BuildID"),
			visible_build_id=plist_data.get("VisibleBuildID"),

			# newer fw
			build_version=plist_data.get("BuildVersion"),
			product_version=plist_data.get("ProductVersion"),

			updater_family_id=plist_data["UpdaterFamilyID"],
			family_id=plist_data["FamilyID"]
		)

	def open_bootloader_img1_file(self) -> IO[bytes]:
		"""Open the bootloader IMG1 file contained within this IPSW"""
		bootloader_name = self.get_manifest().bootloader_name
		if not bootloader_name:
			raise ValueError("no bootloader in this IPSW")
		return self._zipfile.open(bootloader_name, "r")

	def get_bootloader_img1_data(self) -> bytes | None:
		"""Read the entire bootloader IMG1 file, returning its contents in bytes"""
		bootloader_name = self.get_manifest().bootloader_name
		if not bootloader_name:
			return None
		return self._zipfile.read(bootloader_name)

	def get_bootloader_img1_length(self) -> int:
		"""Get the length of the bootloader IMG1 file"""
		bootloader_name = self.get_manifest().bootloader_name
		if not bootloader_name:
			raise ValueError("no bootloader in this IPSW")
		return self._zipfile.getinfo(self.get_manifest().bootloader_name).file_size

	def open_firmware_mse_file(self) -> IO[bytes]:
		"""Open the payload MSE file contained within this IPSW"""
		manifest = self.get_manifest()
		return self._zipfile.open(manifest.firmware_name, "r")

	def get_firmware_mse_data(self) -> bytes:
		"""Read the entire payload MSE file, returning its contents in bytes"""
		return self._zipfile.read(self.get_manifest().firmware_name)

	def get_firmware_mse_length(self) -> int:
		"""Get the length of the payload MSE file"""
		return self._zipfile.getinfo(self.get_manifest().firmware_name).file_size


def looks_like_it_might_be_an_ipsw(stream: BinaryIO) -> bool:
	"""Determine if a stream looks like it might contain an IPSW file.

	Warning:
		This will return True for all ZIP files, because we can't tell if a given ZIP file is an IPSW until we parse it.
	"""
	four_chars = stream.read(4)
	stream.seek(-len(four_chars), io.SEEK_CUR)
	return four_chars == b"PK\x03\x04"
