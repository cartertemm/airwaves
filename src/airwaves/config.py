"""Settings kept in airwaves.conf in the current folder."""

import configparser

FILE_NAME = "airwaves.conf"
SECTION = "airwaves"


def load():
	"""Returns the settings section. It is empty when the file is missing or unreadable."""
	parser = configparser.ConfigParser()
	try:
		parser.read(FILE_NAME, encoding="utf-8")
	except configparser.Error:
		pass
	if not parser.has_section(SECTION):
		parser.add_section(SECTION)
	return parser[SECTION]


def save(key, value):
	"""Writes one setting, keeping the others. Raises OSError when the file cannot be written."""
	settings = load()
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
