"""
Definitions for iPods and their models, variants, SoCs, and updater family IDs.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from ordered_enum import OrderedEnum


class iPodModel(OrderedEnum):
	"""Enumerates supported iPod models."""
	NANO_3G = "nano_3g"
	NANO_4G = "nano_4g"
	NANO_5G = "nano_5g"
	NANO_6G = "nano_6g"
	NANO_7G = "nano_7g"
	CLASSIC_6G = "classic_6g"  # or 6.5g/7g/7.5g, see https://freemyipod.org/wiki/Classic_6G


class iPodMode(OrderedEnum):
	"""Enumerates the possible modes of an iPod."""
	DISK = "disk"
	"""'Disk mode' here encompasses both modes where the iPod is accessible as a mass storage device:
	the normal mode of the iPod, and 'forced disk mode', usually referred to as just 'disk mode'."""

	DFU = "dfu"
	"""In DFU mode, the iPod accepts a second-stage bootloader in IMG1 format."""

	WTF = "wtf"
	"""In WTF mode (maybe *Where's The Firmware?*), the iPod accepts normal firmware images (like osos) in IMG1 format."""

	@property
	def pretty_name(self):
		return _MODE_NAMES[self]


class iPodSubvariant(OrderedEnum):
	"""Enumerates the subvariants of an iPod model."""

	NANO_7G_2012 = "nano_7g_2012"
	"""The initial iPod nano (7th generation), introduced in October 2012."""
	NANO_7G_2015 = "nano_7g_2015"
	"""The revised iPod nano (7th generation), introduced in July 2015. Referred to as "iPod nano (7th generation Mid 2015)"""
	CLASSIC_6G_INITIAL = "classic_6g_initial"
	"""The initial iPod classic (6th generation)"""
	CLASSIC_6G_REV_A = "classic_6g_rev_A"
	"""Revision A of the iPod classic (6th generation), also known as the 6.5th generation."""
	CLASSIC_6G_REV_B = "classic_6g_rev_B"
	"""Revision B of the iPod classic (6th generation), also known as the 7th generation."""
	CLASSIC_6G_REV_C = "classic_6g_rev_C"
	"""Revision C of the iPod classic (6th generation), also known as the 7.5th generation."""

	def __lt__(self, other):
		# make sure subvariants are sorted properly - this means that classic (6g) comes before classic (6g, Rev A)
		if other is None:
			return False
		return super().__lt__(other)


@dataclasses.dataclass(eq=True, frozen=True)
class iPodTarget:
	"""Represents a target iPod. Targets are used to establish a device's compatibility with firmware."""

	model: iPodModel
	"""The target model of iPod."""
	subvariant: Optional[iPodSubvariant] = None
	"""The target subvariant of iPod, or None if any subvariant is acceptable."""
	mode: Optional[iPodMode] = None
	"""The target mode of iPod, or None if any mode is acceptable."""

	def __gt__(self, other):
		if not isinstance(other, iPodTarget):
			raise NotImplementedError
		return (self.model, self.subvariant, self.mode) > (other.model, other.subvariant, other.mode)

	def with_mode(self, mode: Optional[iPodMode]):
		"""Returns a copy of this iPodTarget with `mode` set to the new mode."""
		return iPodTarget(self.model, self.subvariant, mode)

	def is_compatible_with(self, device: iPodTarget):
		"""check if this iPodTarget is compatible with another, where `self` is the target `device` is being checked against."""
		return (
				(self.model == device.model) and
				# None means any is ok :3
				((self.subvariant == device.subvariant) if self.subvariant else True) and
				((self.mode == device.mode) if self.mode else True)
		)

	def get_pretty_model_name(self) -> str:
		"""Returns a user-friendly name for this target's **model**, like `"iPod nano (6th generation)"`"""
		for (name, target) in _MODEL_NAME_TARGETS:
			if target.is_compatible_with(self):
				return name
		raise ValueError("no pretty model name found")

	def get_pretty_name(self) -> str:
		"""Returns a user-friendly name for this target, like `"iPod nano (6th generation) in WTF mode"`"""
		name = self.get_pretty_model_name()
		if self.mode:
			return f"{name} in {self.mode.pretty_name} mode"
		else:
			return name


_MODEL_NAME_TARGETS: list[tuple[str, iPodTarget]] = [
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

_MODE_NAMES: dict[iPodMode, str] = {
	iPodMode.DFU: "DFU",
	iPodMode.WTF: "WTF",
	iPodMode.DISK: "disk",
}

APPLE_VID = 0x05ac
"""USB vendor ID for Apple Inc."""

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
"""Mapping of USB product IDs to applicable iPod targets."""

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
"""Mapping of iPod updater family IDs to applicable iPod targets."""


class iPodSoC(OrderedEnum):
	"""Enumeration of [SoC](https://en.wikipedia.org/wiki/System_on_a_chip)s used by iPod devices."""
	S5L8740 = "8740"
	"""Samsung S5L8740, used in the iPod nano (7th generation)"""
	S5L8723 = "8723"
	"""Samsung S5L8723, used in the iPod nano (6th generation)"""
	S5L8730 = "8730"
	"""Samsung S5L8730, used in the iPod nano (5th generation)"""
	S5L8720 = "8720"
	"""Samsung S5L8720, used in the iPod nano (4th generation)"""
	S5L8702 = "8702"
	"""Samsung S5L8702, used in the iPod nano (3rd generation) and iPod classic (6th generation)"""

	def get_target_devices(self) -> tuple[iPodTarget, ...]:
		"""List the iPodTargets applicable to this SoC."""
		return tuple(
			iPodTarget(model, None, None)
			for model in _SOC_TO_MODELS[self]
		)


_SOC_TO_MODELS: dict[iPodSoC, tuple[iPodModel]] = {
	iPodSoC.S5L8740: (iPodModel.NANO_7G,),
	iPodSoC.S5L8723: (iPodModel.NANO_6G,),
	iPodSoC.S5L8730: (iPodModel.NANO_5G,),
	iPodSoC.S5L8720: (iPodModel.NANO_4G,),
	iPodSoC.S5L8702: (iPodModel.NANO_3G, iPodModel.CLASSIC_6G),
}

_MODELS_TO_SOC: dict[iPodModel, iPodSoC] = {}
for soc, models in _SOC_TO_MODELS.items():
	for model in models:
		_MODELS_TO_SOC[model] = soc
