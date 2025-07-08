from __future__ import annotations
from dataclasses import dataclass

_YEAR_ALPHABET = "CDFGHJKLMNPQRSTVWXYZ"
_WEEK_ALPHABET = "123456789CDFGHJKLMNPQRTVWXY"


class InvalidSerialNumber(ValueError):
	...


@dataclass
class SerialNumber:
	# https://beetstech.com/blog/decode-meaning-behind-apple-serial-number
	location_code: str  # 3 chars
	manufacturing_year: int  # 2010-2019
	manufacturing_week: int  # 1-53
	identifier: str  # 3 chars
	config_code: str  # 4 chars identifying the model

	@classmethod
	def from_serial(cls, serial: str) -> SerialNumber:
		try:
			if len(serial) != 12:
				raise ValueError()

			half_year = _YEAR_ALPHABET.index(serial[3])

			base_year = half_year // 2
			is_second_half = (half_year % 2) == 1

			year = 2010 + base_year
			week = (
				(1 + _WEEK_ALPHABET.index(serial[4]))
				+ (26 if is_second_half else 0)
			)
		except ValueError:
			raise InvalidSerialNumber(f"invalid serial number {serial!r}") from None

		return cls(
			location_code=serial[:3],
			manufacturing_year=year,
			manufacturing_week=week,
			identifier=serial[5:8],
			config_code=serial[8:12]
		)

	def to_serial(self):
		base_year = (self.manufacturing_year - 2010)
		half_year = base_year * 2

		base_week = self.manufacturing_week
		if base_week > 26:
			base_week -= 26
			half_year += 1

		year_code = _YEAR_ALPHABET[half_year]
		week_code = _WEEK_ALPHABET[base_week - 1]

		return f"{self.location_code}{year_code}{week_code}{self.identifier}{self.config_code}"

	def __repr__(self):
		return f"<SerialNumber manufacturing_year={self.manufacturing_year} manufacturing_week={self.manufacturing_week} {self.to_serial()}>"

