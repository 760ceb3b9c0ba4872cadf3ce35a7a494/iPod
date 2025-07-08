"""
implementation of the iPod Software (IPSW) file format, used to store iPod firmware images.
only iPod-compatible firmware is supported, which is a small subset of IPSW files.
"""

import plistlib
from dataclasses import dataclass
from enum import Enum
from os import PathLike
from pathlib import PurePosixPath
from typing import BinaryIO, IO, Optional
from zipfile import ZipFile

from ipod.definitions import iPodTarget, USB_PID_INDEX


class IPSWKind(Enum):
	PAYLOAD = "payload"
	RECOVERY = "recovery"


def product_type_id_to_usb_pid(product_type_id: int) -> tuple[int, int]:
	return (product_type_id >> 0x10) & 0xFFFF, product_type_id & 0x10


def _get_ipsw_kind(zipfile: ZipFile):
	name_list = zipfile.namelist()
	if "manifest.plist" in name_list:
		return IPSWKind.PAYLOAD
	elif "Restore.plist" in name_list:
		return IPSWKind.RECOVERY
	else:
		raise ValueError("invalid or unknown IPSW")


def get_ipsw_kind(file: str | PathLike | BinaryIO):
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
	FIRMWARE = "firmware"
	WTF = "wtf"


@dataclass
class RecoveryIPSWManifest:
	firmware_directory: str
	product_build_version: str
	supported_product_type_ids: dict[str, list[int]]


class RecoveryIPSWFile(_IPSWFile):
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
		start_part = self.get_img1_filename().split(".")[0]
		return RecoveryIPSWType[start_part]  # seems to work fine idc

	def get_img1_filename(self) -> str:
		pure_path = PurePosixPath(self._get_img1_file_path())
		return pure_path.name

	def get_img1_data(self) -> bytes:
		return self._zipfile.read(self._get_img1_file_path())

	def get_manifest(self) -> RecoveryIPSWManifest:
		raw_data = self._zipfile.read("Restore.plist")
		plist_data = plistlib.loads(raw_data)
		return RecoveryIPSWManifest(
			firmware_directory=plist_data["FirmwareDirectory"],
			product_build_version=plist_data["ProductBuildVersion"],
			supported_product_type_ids=plist_data["SupportedProductTypeIDs"]
		)

	def get_target_device_usb_pids(self) -> list[int]:
		manifest = self.get_manifest()
		type_ids = manifest.supported_product_type_ids["DFU"]

		return [product_type_id_to_usb_pid(type_id)[0] for type_id in type_ids]

	def get_target_devices(self) -> list[iPodTarget]:
		return [USB_PID_INDEX[pid] for pid in self.get_target_device_usb_pids()]


@dataclass()
class PayloadIPSWManifest:
	firmware_name: str
	bootloader_name: str
	updater_family_id: int
	family_id: int
	build_id: Optional[int] = None
	visible_build_id: Optional[int] = None
	build_version: Optional[str] = None
	product_version: Optional[str] = None


class PayloadIPSWFile(_IPSWFile):
	def __init__(self, file: str | PathLike | BinaryIO):
		super().__init__(file)
		if _get_ipsw_kind(self._zipfile) != IPSWKind.PAYLOAD:
			raise ValueError("must be a payload IPSW")

	def get_manifest(self) -> PayloadIPSWManifest:
		raw_data = self._zipfile.read("manifest.plist")
		plist_data = plistlib.loads(raw_data)["FirmwarePayload"]
		return PayloadIPSWManifest(
			firmware_name=plist_data["FirmwareName"],
			bootloader_name=plist_data["BootloaderName"],

			# older fw
			build_id=plist_data.get("BuildID"),
			visible_build_id=plist_data.get("VisibleBuildID"),

			# newer fw
			build_version=plist_data.get("BuildVersion"),
			product_version=plist_data.get("ProductVersion"),

			updater_family_id=plist_data["UpdaterFamilyID"],
			family_id=plist_data["FamilyID"]
		)

	# @contextmanager
	def open_bootloader_img1_file(self) -> IO[bytes]:
		manifest = self.get_manifest()
		return self._zipfile.open(manifest.bootloader_name, "r")
		# yield stream

	def get_bootloader_img1_data(self) -> bytes:
		return self._zipfile.read(self.get_manifest().bootloader_name)

	# @contextmanager
	def open_firmware_mse_file(self) -> IO[bytes]:
		manifest = self.get_manifest()
		return self._zipfile.open(manifest.firmware_name, "r")
		# yield stream

	def get_firmware_mse_data(self) -> bytes:
		return self._zipfile.read(self.get_manifest().firmware_name)
