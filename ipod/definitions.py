"""
definitions for iPod models and updater family IDs
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Optional


class iPodModel(Enum):
	NANO_3G = "nano_3g"
	NANO_4G = "nano_4g"
	NANO_5G = "nano_5g"
	NANO_6G = "nano_6g"
	NANO_7G = "nano_7g"
	CLASSIC_6G = "classic_6g"  # or 6.5g/7g/7.5g, see https://freemyipod.org/wiki/Classic_6G


class iPodMode(Enum):
	DISK = "disk"
	DFU = "dfu"
	WTF = "wtf"

	@property
	def pretty_name(self):
		return MODE_NAMES[self]


class iPodSubvariant(Enum):
	NANO_7G_2012 = "nano_7g_2012"
	NANO_7G_2015 = "nano_7g_2015"
	CLASSIC_6G_INITIAL = "classic_6g_initial"
	CLASSIC_6G_REV_A = "classic_6g_rev_A"
	CLASSIC_6G_REV_B = "classic_6g_rev_B"
	CLASSIC_6G_REV_C = "classic_6g_rev_C"


@dataclasses.dataclass
class iPodTarget:
	# represents a specific target iPod
	model: iPodModel
	subvariant: Optional[iPodSubvariant] = None
	mode: Optional[iPodMode] = None

	def is_compatible_with(self, device: iPodTarget):
		"""check if this iPodTarget is compatible with another (assuming `self` is the target `device` is being checked against)"""
		return (
				(self.model == device.model) and
				# None means any is ok :3
				((self.subvariant == device.subvariant) if self.subvariant else True) and
				((self.mode == device.mode) if self.mode else True)
		)

	def get_pretty_model_name(self) -> str:
		for (name, target) in MODEL_NAME_TARGETS:
			if target.is_compatible_with(self):
				return name
		raise ValueError("no pretty model name found")

	def get_pretty_name(self) -> str:
		name = self.get_pretty_model_name()
		if self.mode:
			return f"{name} in {self.mode.pretty_name} mode"
		else:
			return name


MODEL_NAME_TARGETS: list[tuple[str, iPodTarget]] = [
	("iPod nano (3rd generation)", iPodTarget(iPodModel.NANO_3G)),
	("iPod nano (4th generation)", iPodTarget(iPodModel.NANO_4G)),
	("iPod nano (5th generation)", iPodTarget(iPodModel.NANO_5G)),
	("iPod nano (6th generation)", iPodTarget(iPodModel.NANO_6G)),
	("iPod nano (7th generation Mid 2015)", iPodTarget(iPodModel.NANO_7G, iPodSubvariant.NANO_7G_2015)),
	("iPod nano (7th generation)", iPodTarget(iPodModel.NANO_7G)),

	("iPod classic (6th generation Rev A)", iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_A)),
	("iPod classic (6th generation Rev B)", iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_B)),
	("iPod classic (6th generation Rev C)", iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_C)),
	("iPod classic (6th generation)", iPodTarget(iPodModel.CLASSIC_6G))
]

MODE_NAMES: dict[iPodMode, str] = {
	iPodMode.DFU: "DFU",
	iPodMode.WTF: "WTF",
	iPodMode.DISK: "disk",
}

APPLE_VID = 0x05ac  # apple inc, http://www.linux-usb.org/usb.ids
USB_PID_INDEX: dict[int, iPodTarget] = {
	# https://freemyipod.org/wiki/Modes

	0x1262: iPodTarget(iPodModel.NANO_3G, None, iPodMode.DISK),
	# 0x1223: iPodTarget(iPodModel.NANO_3G, None, iPodMode.DFU),
	0x1224: iPodTarget(iPodModel.NANO_3G, None, iPodMode.DFU),
	0x1242: iPodTarget(iPodModel.NANO_3G, None, iPodMode.WTF),

	0x1263: iPodTarget(iPodModel.NANO_4G, None, iPodMode.DISK),
	0x1225: iPodTarget(iPodModel.NANO_4G, None, iPodMode.DFU),
	0x1243: iPodTarget(iPodModel.NANO_4G, None, iPodMode.WTF),

	0x1265: iPodTarget(iPodModel.NANO_5G, None, iPodMode.DISK),
	0x1231: iPodTarget(iPodModel.NANO_5G, None, iPodMode.DFU),
	0x1246: iPodTarget(iPodModel.NANO_5G, None, iPodMode.WTF),

	0x1266: iPodTarget(iPodModel.NANO_6G, None, iPodMode.DISK),
	0x1232: iPodTarget(iPodModel.NANO_6G, None, iPodMode.DFU),
	0x1248: iPodTarget(iPodModel.NANO_6G, None, iPodMode.WTF),

	0x1267: iPodTarget(iPodModel.NANO_7G, None, iPodMode.DISK),
	0x1234: iPodTarget(iPodModel.NANO_7G, None, iPodMode.DFU),
	0x1249: iPodTarget(iPodModel.NANO_7G, iPodSubvariant.NANO_7G_2012, iPodMode.WTF),
	0x124A: iPodTarget(iPodModel.NANO_7G, iPodSubvariant.NANO_7G_2015, iPodMode.WTF),

	0x1261: iPodTarget(iPodModel.CLASSIC_6G, None, iPodMode.DISK),
	0x1223: iPodTarget(iPodModel.CLASSIC_6G, None, iPodMode.DFU),
	0x1241: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_INITIAL, iPodMode.WTF),
	0x1245: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_A, iPodMode.WTF),
	0x1247: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_B, iPodMode.WTF),
	0x1250: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_C, iPodMode.WTF),
}

UPDATER_FAMILY_ID_INDEX: dict[int, iPodTarget] = {
	# https://freemyipod.org/wiki/Hardware
	26: iPodTarget(iPodModel.NANO_3G),
	31: iPodTarget(iPodModel.NANO_4G),
	34: iPodTarget(iPodModel.NANO_5G),
	36: iPodTarget(iPodModel.NANO_6G),
	37: iPodTarget(iPodModel.NANO_7G, iPodSubvariant.NANO_7G_2012),
	39: iPodTarget(iPodModel.NANO_7G, iPodSubvariant.NANO_7G_2015),

	24: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_INITIAL),
	33: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_A),
	35: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_B),
	38: iPodTarget(iPodModel.CLASSIC_6G, iPodSubvariant.CLASSIC_6G_REV_C),  # guessing for this one.
}
