"""Settings kept in airwaves.conf in the current folder."""

import configparser

FILE_NAME = "airwaves.conf"
SECTION = "airwaves"
PRESETS = "presets"


def read():
	parser = configparser.ConfigParser()
	try:
		parser.read(FILE_NAME, encoding="utf-8")
	except configparser.Error:
		pass
	return parser


def load(section=SECTION):
	"""Returns the section. It is empty when the file is missing or unreadable."""
	parser = read()
	if not parser.has_section(section):
		parser.add_section(section)
	return parser[section]


def save(key, value, section=SECTION):
	"""Writes one setting, keeping the others. Raises OSError when the file cannot be written."""
	settings = load(section)
	settings[key] = str(value)
	with open(FILE_NAME, "w", encoding="utf-8") as file:
		settings.parser.write(file)


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
