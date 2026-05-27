"""
Implementation of the Apple 11- and 12-character serial number format.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

_YEAR_ALPHABET = "CDFGHJKLMNPQRSTVWXYZ"
_WEEK_ALPHABET = "123456789CDFGHJKLMNPQRTVWXY"


class InvalidSerialNumber(ValueError):
	...


@dataclass
class SerialNumber:
	"""
	Represents an Apple serial number.
	Technical details: https://beetstech.com/blog/decode-meaning-behind-apple-serial-number
	"""
	location_code: str
	"""3-character location code of the place of manufacture."""
	manufacturing_year: int
	"""Year of manufacture"""
	manufacturing_week: int
	"""Week number of the date of manufacture"""
	identifier: str
	"""Random 3-character code uniquely identifying a device"""
	config_code: str
	"""4-character configuration code identifying the model of device"""

	@classmethod
	def from_serial(cls, serial: str) -> SerialNumber:
		"""Parse a serial, returning a new SerialNumber."""
		if len(serial) == 12:
			# 2010- serial format
			half_year = _YEAR_ALPHABET.index(serial[3])

			base_year = half_year // 2
			is_second_half = (half_year % 2) == 1

			year = 2010 + base_year
			week = (
					(1 + _WEEK_ALPHABET.index(serial[4]))
					+ (26 if is_second_half else 0)
			)
		elif len(serial) == 11:
			# 2000s serial format
			year = 2000 + int(serial[2])
			week = int(serial[3:5])
		else:
			raise ValueError("invalid serial number")

		return cls(
			location_code=serial[:3],
			manufacturing_year=year,
			manufacturing_week=week,
			identifier=serial[5:8],
			config_code=serial[8:12]
		)

	def to_serial(self) -> str:
		"""Turn this SerialNumber back to a string."""
		# fixme: always creates 2010 serials
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


def calculate_week_start_and_end_dates(year: int, week: int):
	"""Utility to turn a week and year to the monday and sunday dates of that week."""
	monday_date = datetime.datetime.strptime(f"{year}-W{week}-1", "%Y-W%W-%w")
	friday_date = monday_date + datetime.timedelta(days=6)
	return monday_date, friday_date
