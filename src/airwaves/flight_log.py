"""Turns ACARS messages into one readable line each, such as "22:26: Flight Y4 1747 (XA-VLH) from LAS (Las Vegas) to GDL (Guadalajara), position report, at 36,977 ft near PHX (Phoenix)"."""

import functools
import re
from datetime import datetime, timezone

import airportsdata
import numpy as np

# Standard ACARS labels (ARINC 618 and 620). Labels not listed are airline defined.
LABELS = {
	"_\x7f": "link check", "_d": "link check", "00": "emergency report", "2S": "weather request", "2U": "weather report",
	"4M": "cargo information", "51": "time request", "52": "time request", "54": "voice contact request", "57": "position report",
	"5D": "ATIS request", "5P": "ACARS paused", "5R": "position report", "5U": "weather request", "5V": "data link change",
	"5Y": "new ETA", "5Z": "airline message", "7A": "engine report", "7B": "message", "A1": "oceanic clearance",
	"A3": "departure clearance", "A4": "departure clearance confirmed", "A5": "position report request", "A6": "ADS report request",
	"A7": "message for the crew", "A8": "departure slot", "A9": "ATIS report", "AA": "air traffic control message",
	"B1": "oceanic clearance request", "B2": "oceanic clearance readback", "B3": "departure clearance request",
	"B4": "departure clearance confirmed", "B5": "position report", "B6": "ADS report", "B8": "departure slot request",
	"B9": "ATIS request", "BA": "air traffic control message", "C0": "message for the cockpit printer",
	"C1": "message for the cockpit printer", "F3": "radio advisory", "H1": "message", "H2": "weather report", "HX": "message",
	"Q0": "link test", "Q1": "departure and arrival report", "Q2": "ETA report", "Q3": "clock update", "Q4": "voice channel busy",
	"Q5": "message not processed", "Q6": "change from voice to ACARS", "Q7": "delay report", "QA": "left the gate (OUT), fuel report",
	"QB": "took off (OFF)", "QC": "landed (ON)", "QD": "reached the gate (IN), fuel report", "QE": "left the gate (OUT), destination",
	"QF": "took off (OFF), destination", "QG": "left the gate and returned", "QH": "left the gate (OUT)", "QK": "landed",
	"QL": "arrived", "QM": "arrival information", "QN": "diverted", "QP": "left the gate (OUT)", "QQ": "took off (OFF)",
	"QR": "landed (ON)", "QS": "reached the gate (IN)", "QT": "left the gate and returned", "RA": "message for the crew",
	"RB": "reply to a message for the crew", "SA": "data link status", "SQ": "ground station broadcast",
}
# Words in the text that name the message type.
TYPE_WORDS = {"POSRPT": "position report", "POS RPT": "position report"}
TYPE_WORD = re.compile(r"\b(" + "|".join(TYPE_WORDS) + r")\b")
AIRPORT_PAIR = re.compile(r"\b([A-Z]{4})/([A-Z]{4})\b")
# Degrees and minutes to a tenth (N33080W111591), or decimal degrees (N33.133 W111.985).
POSITION = re.compile(r"(?:/POS\s*)?([NS])\s?(\d{2})(\d{2})(\d)\s?,?\s?([EW])\s?(\d{3})(\d{2})(\d)\b")
DECIMAL_POSITION = re.compile(r"(?:/POS\s*)?([NS])\s?(\d{1,2}\.\d+)\s?,?\s?([EW])\s?(\d{1,3}\.\d+)")
FIELD = re.compile(r"/(ALT|MCH|FOB|ETA)\s*([+-]?\d+)")
FLIGHT = re.compile(r"([A-Z0-9]{2})0*(\d+[A-Z]?)")
# Past this distance, a position shows how far it is from the closest airport.
NEAR_KM = 50
EARTH_RADIUS_KM = 6371


@functools.cache
def airports():
	"""Returns the airports by ICAO code."""
	return airportsdata.load("ICAO")


@functools.cache
def airport_index():
	"""Returns the airports with an IATA code, and their latitudes and longitudes in radians."""
	known = [airport for airport in airports().values() if airport["iata"]]
	return known, np.radians([airport["lat"] for airport in known]), np.radians([airport["lon"] for airport in known])


def airport_name(airport):
	return f"{airport['iata'] or airport['icao']} ({airport['city'] or airport['name']})"


def nearest_airport(lat, lon):
	"""Returns the closest airport with an IATA code, and its distance in km."""
	known, lats, lons = airport_index()
	lat, lon = np.radians(lat), np.radians(lon)
	# Haversine distance.
	a = np.sin((lats - lat) / 2) ** 2 + np.cos(lat) * np.cos(lats) * np.sin((lons - lon) / 2) ** 2
	distances = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))
	index = int(np.argmin(distances))
	return known[index], distances[index]


def format_flight(flight):
	"""Splits the airline from the number and drops the zeros before it: "UA0123" becomes "UA 123"."""
	match = FLIGHT.fullmatch(flight)
	return f"{match.group(1)} {match.group(2)}" if match else flight


def find_position(text):
	"""Returns (lat, lon, text without the position), or None."""
	match = POSITION.search(text)
	if match:
		ns, lat_deg, lat_min, lat_tenth, ew, lon_deg, lon_min, lon_tenth = match.groups()
		lat = int(lat_deg) + (int(lat_min) + int(lat_tenth) / 10) / 60
		lon = int(lon_deg) + (int(lon_min) + int(lon_tenth) / 10) / 60
	else:
		match = DECIMAL_POSITION.search(text)
		if not match:
			return None
		ns, lat, ew, lon = match.groups()
		lat, lon = float(lat), float(lon)
	if lat > 90 or lon > 180:
		return None
	lat = -lat if ns == "S" else lat
	lon = -lon if ew == "W" else lon
	return lat, lon, text[:match.start()] + " " + text[match.end():]


def describe_position(lat, lon, altitude):
	airport, distance = nearest_airport(lat, lon)
	place = f"near {airport_name(airport)}" if distance <= NEAR_KM else f"{distance:,.0f} km from {airport_name(airport)}"
	return f"at {altitude} {place}" if altitude else place


def utc_to_local(hhmm):
	"""Turns an HHMM time in UTC into HH:MM local time, or returns None if it is not a time."""
	hours, minutes = int(hhmm[:-2] or 0), int(hhmm[-2:])
	if hours > 23 or minutes > 59:
		return None
	return datetime.now(timezone.utc).replace(hour=hours, minute=minutes).astimezone().strftime("%H:%M")


def describe(message):
	"""Returns message as one readable line. Text it cannot read follows " | "."""
	text = message.text
	parts = []
	label_type = LABELS.get(message.label)
	type_word = TYPE_WORD.search(text)
	if type_word:
		text = text[:type_word.start()] + " " + text[type_word.end():]
	parts.append(TYPE_WORDS[type_word.group(1)] if type_word else label_type or f"label {message.label} message")
	route = ""
	pair = AIRPORT_PAIR.search(text)
	if pair and pair.group(1) in airports() and pair.group(2) in airports():
		route = f" from {airport_name(airports()[pair.group(1)])} to {airport_name(airports()[pair.group(2)])}"
		text = text[:pair.start()] + " " + text[pair.end():]
	fields = {}
	for match in FIELD.finditer(text):
		fields.setdefault(match.group(1), match.group(2))
	altitude = f"{int(fields['ALT']):,} ft" if "ALT" in fields else ""
	eta = utc_to_local(fields["ETA"]) if "ETA" in fields else None
	understood = {"ALT", "MCH", "FOB"} | ({"ETA"} if eta else set())
	text = FIELD.sub(lambda match: " " if match.group(1) in understood else match.group(0), text)
	position = find_position(text)
	if position:
		lat, lon, text = position
		parts.append(describe_position(lat, lon, altitude))
	elif altitude:
		parts.append(f"at {altitude}")
	if "MCH" in fields:
		parts.append(f"Mach 0.{fields['MCH'].lstrip('+')}")
	if "FOB" in fields:
		parts.append(f"fuel {int(fields['FOB'])}")
	if eta:
		parts.append(f"ETA {eta}")
	if message.registration:
		text = re.sub(r"\.?\b" + re.escape(message.registration) + r"\b", " ", text)
	number = FLIGHT.fullmatch(message.flight)
	if number:
		# The flight number and the day of the month, such as 1747/06.
		text = re.sub(r"\b0*" + re.escape(number.group(2)) + r"/\d{2}\b", " ", text)
	unread = " ".join(word for word in text.split() if word.strip("/.,-"))
	time = message.time.astimezone().strftime("%H:%M")
	if message.flight:
		who = f"Flight {format_flight(message.flight)} ({message.registration})" if message.registration else f"Flight {format_flight(message.flight)}"
	elif message.block_id.isdigit():
		who = message.registration or "Aircraft"
	else:
		who = f"Ground to {message.registration}" if message.registration else "Ground"
	line = f"{time}: {who}{route}, {', '.join(parts)}"
	return f"{line} | {unread}" if unread else line
