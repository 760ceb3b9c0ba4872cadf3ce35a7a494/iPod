# noinspection PyProtectedMember,PyUnresolvedReferences
from plistlib import _PlistParser


# noinspection PyAttributeOutsideInit
class iPodPlistParser(_PlistParser):
	"""
	Apple appears to have a non-compliant plist implementation for certain iPods.
	Rather than a dictionary, the array type is used for objects with integer keys, like:
		<array><key>1234</key><string>Value</string></array>
	This HACK patches the standard plistlib with support for this broken plist format.
	"""

	def end_key(self):
		if self.current_key or not isinstance(self.stack[-1], (dict, list)):
			raise ValueError("unexpected key at line %d" % self.parser.CurrentLineNumber)
		if isinstance(self.stack[-1], list) and len(self.stack[-1]) == 0:
			# print(f"Fixing malformed array at line {self.parser.CurrentLineNumber}")
			self.stack[-1] = {}
		self.current_key = self.get_data()
