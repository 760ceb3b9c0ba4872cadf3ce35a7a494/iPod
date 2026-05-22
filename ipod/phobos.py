from __future__ import annotations

import plistlib
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from .definitions import UPDATER_FAMILY_ID_INDEX, iPodTarget, USB_PID_INDEX
from .utils import numeric_build_id_to_string

APPLE_PHOBOS_URL = "https://itunes.apple.com/WebObjects/MZStore.woa/wa/com.apple.jingle.appserver.client.MZITunesClientCheck/version"
HTTP_DNLD_HOST = "appldnld.apple.com"
HTTPS_DNLD_HOST = "secure-appldnld.apple.com"
EDGESUITE_DNLD_HOST = "appldnld.apple.com.edgesuite.net"


class BaseAvailableSoftware:
	def get_target_device(self) -> iPodTarget: ...
	def _version_as_tuple(self) -> tuple[int, ...]: ...

	def __gt__(self, other):
		if not isinstance(other, self.__class__):
			raise NotImplementedError

		return (self.get_target_device(), self._version_as_tuple()) > (other.get_target_device(), other._version_as_tuple())


@dataclass(eq=True, frozen=True)
class AvailableSoftwareUpdate(BaseAvailableSoftware):
	updater_family_id: int
	build_id: Optional[int]
	visible_build_id: Optional[int]
	product_version: Optional[str]
	build_version: Optional[str]
	firmware_url: str
	documentation_url: str

	def _version_as_tuple(self):
		if self.product_version:
			return tuple(map(int, self.product_version.split(".")))
		else:
			build_id = self.visible_build_id
			return build_id >> 24 & 0b1111, build_id >> 20 & 0b1111, build_id >> 16 & 0b1111

	def get_target_device(self) -> iPodTarget | None:
		return UPDATER_FAMILY_ID_INDEX.get(self.updater_family_id)

	def is_compatible_with(self, target: iPodTarget) -> bool:
		return self.get_target_device().is_compatible_with(target)

	def get_pretty_version_name(self):
		version_part = self.product_version or numeric_build_id_to_string(self.visible_build_id)
		detailed_version_part = self.build_version or numeric_build_id_to_string(self.build_id)
		return f"{version_part} ({detailed_version_part})"

	def __repr__(self):
		try:
			target = self.get_target_device()
		except KeyError:
			target = None

		if self.product_version:
			version = f"{self.product_version} ({self.build_version})"
		else:
			version = f"{numeric_build_id_to_string(self.visible_build_id)} ({numeric_build_id_to_string(self.build_id)})"

		return f"{self._version_as_tuple()} <{self.__class__.__name__}: {version} for {target.get_pretty_model_name() if target else 'unknown iPod'}>"


@dataclass(kw_only=True, frozen=True)
class AvailableRecoverySoftware(BaseAvailableSoftware):
	usb_pid: int
	build_version: Optional[str]
	firmware_url: str

	def _version_as_tuple(self):
		if "." in self.build_version:
			return tuple(map(int, self.build_version.split("."))) if self.build_version else (0)
		else:
			return (int(self.build_version[3:]), )

	def get_target_device(self) -> iPodTarget:
		return USB_PID_INDEX[self.usb_pid]

	def __repr__(self):
		return f"<{self.__class__.__name__}: {self.build_version} for {self.get_target_device().get_pretty_name()}>"


@dataclass(kw_only=True)
class AvailableUpdates:
	recovery_software: set[AvailableRecoverySoftware]
	software_updates: set[AvailableSoftwareUpdate]

	def extend_with(self, other: AvailableUpdates):
		self.recovery_software.update(other.recovery_software)
		self.software_updates.update(other.software_updates)

	@classmethod
	def from_phobos_plist(cls, plist_data: str | bytes, *, fix_urls: bool = True):
		"""
		Create an AvailableUpdates instance from Apple Phobos data in plist format
		"""
		data = plistlib.loads(plist_data)

		def _fix_url(url: str):
			if fix_urls:
				return fix_appldnld_url(url)
			else:
				return url

		recovery_software: set[AvailableRecoverySoftware] = set()
		seen_firmware_ids = set()
		for by_version_data in data["MobileDeviceSoftwareVersionsByVersion"].values():
			versions_data = by_version_data["RecoverySoftwareVersions"]
			# print(versions_data)
			for firmware_data_list in (
				versions_data["WTF"] if "WTF" in versions_data else None,
				versions_data["Firmware"]["DFU"] if "Firmware" in versions_data else None
			):
				if not firmware_data_list:
					continue
				for firmware_id, firmware_data in firmware_data_list.items():
					firmware_id = int(firmware_id)
					if firmware_id in seen_firmware_ids:
						continue
					seen_firmware_ids.add(firmware_id)

					usb_pid = firmware_id >> 16
					if usb_pid not in USB_PID_INDEX:
						# then we dont support this iPod, so ignore it
						continue

					recovery_software.add(AvailableRecoverySoftware(
						usb_pid=usb_pid,
						build_version=firmware_data["BuildVersion"],
						firmware_url=_fix_url(firmware_data["FirmwareURL"])
					))

		software_updates: set[AvailableSoftwareUpdate] = {
			AvailableSoftwareUpdate(
				updater_family_id=int(item["UpdaterFamilyID"]),
				build_id=int(item["BuildID"]) if "BuildID" in item else None,
				firmware_url=_fix_url(item["FirmwareURL"]),
				documentation_url=_fix_url(item["DocumentationURL"]),
				visible_build_id=int(item["VisibleBuildID"]) if "VisibleBuildID" in item else None,
				product_version=item.get("ProductVersion"),
				build_version=item.get("BuildVersion")
			) for item in data["iPodSoftwareVersions"].values()
		}
		software_updates = set(update for update in software_updates if update.get_target_device() is not None)

		return cls(
			software_updates=software_updates,
			recovery_software=recovery_software
		)

	def recovery_software_by_usb_pid(self) -> dict[int, list[AvailableRecoverySoftware]]:
		result = {}

		for update in self.recovery_software:
			key = update.usb_pid
			if key is None:
				continue
			if key not in result:
				result[key] = []
			result[key].append(update)

		for update_list in result.values():
			update_list.sort()

		return result

	def software_updates_by_updater_family_id(self) -> dict[int, list[AvailableSoftwareUpdate]]:
		result = {}

		for update in self.software_updates:
			key = update.updater_family_id
			if key is None:
				continue
			if key not in result:
				result[key] = []
			result[key].append(update)

		for update_list in result.values():
			update_list.sort()

		return result


def fix_appldnld_url(phobos_url: str):
	"""Fix an appldnld CDN URL by updating host and changing the scheme to https """
	url = urlsplit(phobos_url)

	if url.hostname == EDGESUITE_DNLD_HOST:
		path = "/" + "/".join(url.path.split("/")[2:])
	elif url.hostname in {HTTP_DNLD_HOST, HTTPS_DNLD_HOST}:
		path = url.path
	else:
		raise ValueError("Invalid URL")

	return urlunsplit((
		"https", HTTPS_DNLD_HOST, path, url.query, url.fragment
	))


HISTORICAL_AVAILABLE_UPDATES = AvailableUpdates(
	recovery_software=set(),
	software_updates={
		# iPod classic (6th generation)
		AvailableSoftwareUpdate(24, 151224320, 17006592, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-3940.20071115.0Iun5/iPod_24.1.0.3.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-3940.20071115.0Iun5/iPodDocumentation_24.1.0.3.ipd"),
		AvailableSoftwareUpdate(24, 152076288, 17858560, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4010.20080115.Ad4rF/iPod_24.1.1.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4010.20080115.Ad4rF/iPodDocumentation_24.1.1.ipd"),
		AvailableSoftwareUpdate(24, 152207360, 17989632, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4306.20080430.Gtr54/iPod_24.1.1.2.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4306.20080430.Gtr54/iPodDocumentation_24.1.1.2.ipd"),
		AvailableSoftwareUpdate(24, 152141824, 17924096, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4275.20080206.PdpOd/iPod_24.1.1.1.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4275.20080206.PdpOd/iPodDocumentation_24.1.1.1.ipd"),
		AvailableSoftwareUpdate(24, 152207360, 17989632, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4306.20080430.Gtr54/iPod_24.1.1.2.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4306.20080430.Gtr54/iPodDocumentation_24.1.1.2.ipd"),

		# iPod classic (6th generation Rev A)
		AvailableSoftwareUpdate(33, 151027712, 33587200, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4962.20080909.Aaqs3/iPod_33.2.0.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4962.20080909.Aaqs3/iPodDocumentation_33.2.0.ipd"),
		AvailableSoftwareUpdate(33, 151093248, 33652736, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5740.20081111.ZaU7Y/iPod_33.2.0.1.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5740.20081111.ZaU7Y/iPodDocumentation_33.2.0.1.ipd"),

		# iPod classic (6th generation Rev B)
		AvailableSoftwareUpdate(35, 151158784, 33718272, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-6797.20090909.3uTfE/iPod_35.2.0.2.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-6797.20090909.3uTfE/iPodDocumentation_35.2.0.2.ipd"),
		AvailableSoftwareUpdate(35, 151224320, 33783808, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7155.20090925.Ju879/iPod_35.2.0.3.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7155.20090925.Ju879/iPodDocumentation_35.2.0.3.ipd"),
		AvailableSoftwareUpdate(35, 151289856, 33849344, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7299.20091217.Bghyt/iPod_35.2.0.4.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7299.20091217.Bghyt/iPodDocumentation_35.2.0.4.ipd"),

		# iPod classic (6th generation Rev C)
		AvailableSoftwareUpdate(38, 151355392, 33914880, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-8552.20121203.Bile3/iPod_38.2.0.5.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-8552.20121203.Bile3/iPodDocumentation_38.2.0.5.ipd"),

		# iPod nano (3rd generation)
		AvailableSoftwareUpdate(26, 151158784, 16941056, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-3930.20071005.94rVg/iPod_26.1.0.2.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-3930.20071005.94rVg/iPodDocumentation_26.1.0.2.ipd"),

		# iPod nano (4th generation)
		AvailableSoftwareUpdate(31, 167804928, 16809984, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4637.20080909.vfH8i/iPod_31.1.0.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4637.20080909.vfH8i/iPodDocumentation_31.1.0.ipd"),
		AvailableSoftwareUpdate(31, 167936000, 16941056, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5529.20080915.3ngi4/iPod_31.1.0.2.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5529.20080915.3ngi4/iPodDocumentation_31.1.0.2.ipd"),
		AvailableSoftwareUpdate(31, 168001536, 17006592, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5583.20081111.Bhyui/iPod_31.1.0.3.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5583.20081111.Bhyui/iPodDocumentation_31.1.0.3.ipd"),
		AvailableSoftwareUpdate(31, 168067072, 17072128, None, None, "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5808.20090805.Fvgtr/iPod_31.1.0.4.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5808.20090805.Fvgtr/iPodDocumentation_31.1.0.4.ipd"),

		# iPod nano (5th generation)
		AvailableSoftwareUpdate(34, None, None, "1.0.1", "34A10006", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7165.20090909.AzPKm/iPod_1.0.1_34A10006.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7165.20090909.AzPKm/iPodDocumentation_1.0.1_34A10006.ipd"),
		AvailableSoftwareUpdate(34, None, None, "1.0.2", "34A20020", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7408.20091109.Kef5t/iPod_1.0.2_34A20020.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7408.20091109.Kef5t/iPodDocumentation_1.0.2_34A20020.ipd"),

		# iPod nano (6th generation)
		AvailableSoftwareUpdate(36, None, None, "1.0", "36A00403", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-9054.20100907.VKPt5/iPod_1.0_36A00403.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-9054.20100907.VKPt5/iPodDocumentation_1.0_36A00403.ipd"),
		AvailableSoftwareUpdate(36, None, None, "1.1", "36B00109", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-9358.20110221.9a5fF/iPod_1.1_36B00109.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-9358.20110221.9a5fF/iPodDocumentation_1.1_36B00109.ipd"),
		AvailableSoftwareUpdate(36, None, None, "1.2", "36B10147", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-1920.20111004.CpeEw/iPod_1.2_36B10147.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-1920.20111004.CpeEw/iPodDocumentation_1.2_36B10147.ipd"),

		# iPod nano (7th generation)
		AvailableSoftwareUpdate(37, None, None, "1.0.2", "37A20067", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-7265.20121212.WnBg0/iPod_1.0.2_37A20067.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-7265.20121212.WnBg0/iPodDocumentation_1.0.2_37A20067.ipd"),
		AvailableSoftwareUpdate(37, None, None, "1.0.3", "37A30172", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-9962.20131211.Aqaqa/iPod_1.0.3_37A30172.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/041-9962.20131211.Aqaqa/iPodDocumentation_1.0.3_37A30172.ipd"),
		AvailableSoftwareUpdate(37, None, None, "1.0.4", "37A40005", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/031-26260-201500810-D2BC269E-3FBC-11E5-885A-067B3A53DB92/iPod_1.0.4_37A40005.ipsw", "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/031-26260-201500810-D2BC269E-3FBC-11E5-885A-067B3A53DB92/iPodDocumentation_1.0.4_37A40005.ipd"),

		# iPod nano (7th generation Mid 2015)
		AvailableSoftwareUpdate(39, None, None, "1.1.1", "39A00025", "https://secure-appldnld.apple.com/ipod/sbml/osx/bundles/031-25237-20150715-D737390E-1C1F-11E5-9274-0ACEBE268FF7/iPod_1.1.1_39A00025.ipsw", "https://secure-appldnld.apple.com/ipod/sbml/osx/bundles/031-25237-20150715-D737390E-1C1F-11E5-9274-0ACEBE268FF7/iPodDocumentation_1.1.1_39A00025.ipd"),
		AvailableSoftwareUpdate(39, None, None, "1.1.2", "39A10023", "https://secure-appldnld.apple.com/ipod/sbml/osx/bundles/031-59796-20160525-8E6A5D46-21FF-11E6-89D1-C5D3662719FC/iPod_1.1.2_39A10023.ipsw", "https://secure-appldnld.apple.com/ipod/sbml/osx/bundles/031-59796-20160525-8E6A5D46-21FF-11E6-89D1-C5D3662719FC/iPodDocumentation_1.1.2_39A10023.ipd")
	}
)
