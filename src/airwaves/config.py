"""Settings kept in airwaves.conf in the current folder."""

import configparser
import os

FILE_NAME = "airwaves.conf"
TEMPORARY_NAME = FILE_NAME + ".tmp"
SECTION = "airwaves"
PRESETS = "presets"


class DamagedFile(OSError):
	"""The file has an error. Saving would drop every setting after it, so the file is left as it is."""


def read(strict=False):
	"""Returns the parser. When the file has an error, the parser holds only the settings above it, or strict raises DamagedFile."""
	parser = configparser.ConfigParser(interpolation=None)
	try:
		parser.read(FILE_NAME, encoding="utf-8")
	except configparser.Error as error:
		if strict:
			details = " ".join(str(error).split())
			raise DamagedFile(f"It has an error, so it was left as it is. Fix or delete the line named here: {details}") from error
	return parser


def load(section=SECTION, strict=False):
	"""Returns the section. It is empty when the file is missing. Pass strict when the section will be saved."""
	parser = read(strict)
	if not parser.has_section(section):
		parser.add_section(section)
	return parser[section]


def write(parser):
	# A crash while writing leaves the old file whole.
	with open(TEMPORARY_NAME, "w", encoding="utf-8") as file:
		parser.write(file)
	os.replace(TEMPORARY_NAME, FILE_NAME)


def save(key, value, section=SECTION):
	"""Writes one setting, keeping the others. Raises OSError when the file cannot be written or has an error."""
	settings = load(section, strict=True)
	settings[key] = str(value)
	write(settings.parser)


def remove(key, section=SECTION):
	"""Deletes one setting, keeping the others. Raises OSError when the file cannot be written or has an error."""
	settings = load(section, strict=True)
	if key in settings:
		del settings[key]
		write(settings.parser)


def get_int(settings, key, default, low, high):
	"""Returns the setting as an integer from low to high, or default when it is missing or invalid."""
	try:
		value = settings.getint(key)
	except ValueError:
		return default
	if value is None or not low <= value <= high:
		return default
	return value


def presets():
	"""Returns the presets as {number: text}, sorted by number. Keys that are not positive integers are left out."""
	found = {}
	for key, text in load(PRESETS).items():
		if key.isdigit() and int(key) > 0:
			found[int(key)] = text.strip()
	return dict(sorted(found.items()))


def next_preset_number():
	"""Returns the smallest preset number not in use."""
	used = presets()
	number = 1
	while number in used:
		number += 1
	return number
