import argparse
import html
import http.cookiejar
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

ZIP_PATTERN = re.compile(r"\d{5}")
TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
ROW_PATTERN = re.compile(r"<tr>(.*?)</tr>", re.S)
RESULT_CELL_PATTERN = re.compile(r'<td class="(?:even|odd)_row rowsize (\w+)_col[^"]*">(.*?)</td>', re.S)
CALL_PATTERN = re.compile(r"<b>(.*?)</b>(?:.*?\((.*?)\))?", re.S)
INFO_ID_PATTERN = re.compile(r'href="/info/([^"?]+)')
CANONICAL_PATTERN = re.compile(r'<link rel="canonical" href="[^"]*/info/([^"]+)">')
SIGNAL_PATTERN = re.compile(r"vu-(\d)\.gif")
FORMAT_PATTERN = re.compile(r'<span class="max1">(.*?)</span>', re.S)
LOCATION_PATTERN = re.compile(r"listening range of(.*?)\.\s*\(", re.S)
COORDINATES_PATTERN = re.compile(r"loc=(-?[\d.]+)%2C(-?[\d.]+)")
HEADING_PATTERN = re.compile(r"<h1[^>]*>(\S+) ([\d.]+) (MHz|kHz)</h1>")
CITY_PATTERN = re.compile(r'<span class="city_size"><b>(.*?)</b></span>')
SLOGAN_PATTERN = re.compile(r'<span class="city_size"><i>(.*?)</i></span>')
STATION_FORMAT_PATTERN = re.compile(r"(Parent )?Station Format: <i>(.*?)</i>")
OWNER_PATTERN = re.compile(r"<b>Station Owner:</b><br>(.*?)<br>", re.S)
ADDRESS_PATTERN = re.compile(r"Address:</b>, (.*?)</td>", re.S)
TECH_ROW_PATTERN = re.compile(r'<td class="tech_label[^"]*"><b>(.*?)</b></td><td class="tech_value">(.*?)</td>', re.S)
TRANSMITTER_PATTERN = re.compile(r'<td class="xltr"><a href="/info/(.*?)">(.*?)</a></td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\((.*?)\)</td>', re.S)
PREVIOUS_CALL_PATTERN = re.compile(r'<td class="prev-call-call">(.*?)</td><td class="prev-call-date rt">first used (.*?)</td>', re.S)
CONSTRUCTION_PERMIT_MARKER = "Construction Permit:"
RESULTS_MARKER = "Try another search"
CONSTRUCTION_PERMIT_LABEL = "CP"
NO_VALUE = "none"
SIGNAL_LABELS = {1: "very weak", 2: "weak", 3: "moderate", 4: "strong", 5: "very strong"}
BAND_UNITS = (("FM", "MHz"), ("AM", "kHz"))


def clean(fragment):
	text = html.unescape(TAG_PATTERN.sub(" ", fragment)).replace("\xa0", " ")
	return SPACE_PATTERN.sub(" ", text).replace(" ,", ",").strip()


def find(pattern, text, group=1):
	match = pattern.search(text)
	return clean(match.group(group)) if match and match.group(group) else ""


@dataclass
class Station:
	call_sign: str
	station_id: str
	band: str
	frequency: float
	distance_miles: float
	signal_strength: int
	city: str
	state: str
	school: str
	format: str
	parent_call_sign: str
	construction_permit: bool
	has_stream: bool

	@property
	def signal_label(self):
		return SIGNAL_LABELS.get(self.signal_strength, "")


@dataclass
class SearchResult:
	location: str
	latitude: float | None
	longitude: float | None
	stations: list[Station]


@dataclass
class Transmitter:
	call_sign: str
	station_id: str
	frequency: str
	city: str
	power: str


@dataclass
class PreviousCallSign:
	call_sign: str
	first_used: str


@dataclass
class StationInfo:
	station_id: str
	call_sign: str
	frequency: float
	unit: str
	city: str
	state: str
	slogan: str
	format: str
	website: str
	audio_feed: str
	owner: str
	address: str
	phone: str
	fax: str
	from_parent_station: bool
	technical: dict[str, str] = field(default_factory=dict)
	construction_permit: dict[str, str] = field(default_factory=dict)
	additional_transmitters: list[Transmitter] = field(default_factory=list)
	previous_call_signs: list[PreviousCallSign] = field(default_factory=list)


class RadioLocator:
	BASE_URL = "https://radio-locator.com"
	HEADERS = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
		"Referer": "https://radio-locator.com/",
	}

	def __init__(self):
		self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
		self.has_session = False

	def get(self, path, params=None):
		if not self.has_session:
			self.has_session = True
			self.get("/")
		url = self.BASE_URL + path
		if params:
			url += "?" + urllib.parse.urlencode(params)
		request = urllib.request.Request(url, headers=self.HEADERS)
		with self.opener.open(request) as response:
			return response.read().decode("utf-8", errors="replace")

	def search(self, zip_code):
		page = self.get("/cgi-bin/locate", {"select": "city", "city": zip_code})
		if RESULTS_MARKER not in page:
			raise RuntimeError("radio-locator did not return a results page")
		return self.parse_search(page)

	def station_info(self, station_id):
		page = self.get(f"/info/{urllib.parse.quote(station_id)}")
		if not HEADING_PATTERN.search(page):
			raise RuntimeError(f"radio-locator did not return a station page for {station_id}")
		return self.parse_station_info(station_id, page)

	def lookup(self, call_sign):
		page = self.get("/cgi-bin/finder", {"call": call_sign, "sr": "Y", "s": "C"})
		if HEADING_PATTERN.search(page):
			return [self.parse_station_info(find(CANONICAL_PATTERN, page), page)]
		return [self.station_info(station_id) for station_id in dict.fromkeys(INFO_ID_PATTERN.findall(page))]

	@staticmethod
	def parse_search(page):
		stations = []
		for row in ROW_PATTERN.findall(page):
			cells = dict(RESULT_CELL_PATTERN.findall(row))
			call_match = CALL_PATTERN.search(cells.get("call", ""))
			if not call_match:
				continue
			note = clean(call_match.group(2) or "")
			frequency, band = clean(cells["freq"]).split()
			city, _, state = clean(cells["city"]).rpartition(", ")
			signal = SIGNAL_PATTERN.search(cells["dist"])
			stations.append(Station(
				call_sign=clean(call_match.group(1)),
				station_id=find(INFO_ID_PATTERN, cells["info"]),
				band=band,
				frequency=float(frequency),
				distance_miles=float(clean(cells["dist"]).split()[0]),
				signal_strength=int(signal.group(1)) if signal else 0,
				city=city,
				state=state,
				school=clean(cells["school"]),
				format=find(FORMAT_PATTERN, cells["format"]),
				parent_call_sign="" if note == CONSTRUCTION_PERMIT_LABEL else note,
				construction_permit=note == CONSTRUCTION_PERMIT_LABEL,
				has_stream="bc=y" in cells["bc"],
			))
		coordinates = COORDINATES_PATTERN.search(page)
		return SearchResult(
			location=find(LOCATION_PATTERN, page),
			latitude=float(coordinates.group(1)) if coordinates else None,
			longitude=float(coordinates.group(2)) if coordinates else None,
			stations=stations,
		)

	@staticmethod
	def parse_station_info(station_id, page):
		heading = HEADING_PATTERN.search(page)
		city, _, state = find(CITY_PATTERN, page).rpartition(", ")
		format_match = STATION_FORMAT_PATTERN.search(page)
		licensed, _, permit = page.partition(CONSTRUCTION_PERMIT_MARKER)

		def labeled(label, end):
			match = re.search(rf"<b>(?:Parent )?{label}:</b>(.*?){end}", page, re.S)
			value = clean(match.group(1)) if match else ""
			return "" if value == NO_VALUE else value

		def tech_rows(fragment):
			return {clean(label): clean(value) for label, value in TECH_ROW_PATTERN.findall(fragment)}

		return StationInfo(
			station_id=station_id,
			call_sign=heading.group(1),
			frequency=float(heading.group(2)),
			unit=heading.group(3),
			city=city,
			state=state,
			slogan=find(SLOGAN_PATTERN, page).strip('"'),
			format=clean(format_match.group(2)) if format_match else "",
			website=labeled("Website", "</p>"),
			audio_feed=labeled("Audio Feed", "</p>"),
			owner=find(OWNER_PATTERN, page),
			address=find(ADDRESS_PATTERN, page.replace("<br>", ", ")),
			phone=labeled("Phone", "<br>"),
			fax=labeled("Fax", "<br>"),
			from_parent_station=bool(format_match and format_match.group(1)),
			technical=tech_rows(licensed),
			construction_permit=tech_rows(permit),
			additional_transmitters=[Transmitter(clean(call), station, clean(frequency), clean(city), clean(power)) for station, call, frequency, city, power in TRANSMITTER_PATTERN.findall(page)],
			previous_call_signs=[PreviousCallSign(clean(call), clean(date)) for call, date in PREVIOUS_CALL_PATTERN.findall(page)],
		)


def format_call(station):
	if station.construction_permit:
		return f"{station.call_sign} (CP)"
	if station.parent_call_sign:
		return f"{station.call_sign} ({station.parent_call_sign})"
	return station.call_sign


def print_info(info):
	print(f"\n{info.call_sign} {info.frequency:g} {info.unit}")
	fields = (
		("Station ID", info.station_id),
		("City", f"{info.city}, {info.state}"),
		("Slogan", info.slogan),
		("Format", info.format),
		("Website", info.website),
		("Audio feed", info.audio_feed),
		("Owner", info.owner),
		("Address", info.address),
		("Phone", info.phone),
		("Fax", info.fax),
	)
	for label, value in fields:
		if value:
			print(f"  {label}: {value}")
	if info.from_parent_station:
		print("  (Format, website and address are for the parent station)")
	sections = (("Technical details", info.technical), ("Construction permit", info.construction_permit))
	for title, details in sections:
		if details:
			print(f"\n  {title}:")
			for label, value in details.items():
				print(f"    {label}: {value}")
	if info.additional_transmitters:
		print("\n  Additional transmitters:")
		for t in info.additional_transmitters:
			print(f"    {t.call_sign} ({t.station_id}) {t.frequency}, {t.city}, {t.power}")
	if info.previous_call_signs:
		print("\n  Previous call signs:")
		for previous in info.previous_call_signs:
			print(f"    {previous.call_sign}, first used {previous.first_used}")


def show_info(call_sign):
	locator = RadioLocator()
	stations = locator.lookup(call_sign) if "-" not in call_sign else [locator.station_info(call_sign.upper())]
	if not stations:
		print(f"No station found for {call_sign}.")
	for info in stations:
		print_info(info)


def show_search(zip_code):
	zip_code = zip_code.strip()
	if not ZIP_PATTERN.fullmatch(zip_code):
		print("Enter a 5 digit zip code.")
		return
	result = RadioLocator().search(zip_code)
	if not result.stations:
		print("No stations found.")
		return
	print(f"Stations near {result.location}")
	for band, unit in BAND_UNITS:
		band_stations = sorted((s for s in result.stations if s.band == band), key=lambda s: s.frequency)
		print(f"\n{band}: {len(band_stations)} found")
		print(f"{'Freq (' + unit + ')':<11}{'Call':<20}{'Distance':<11}{'Signal':<13}{'City':<22}{'State':<7}{'Format':<24}School")
		for s in band_stations:
			print(f"{s.frequency:<11g}{format_call(s):<20}{f'{s.distance_miles:g} mi':<11}{s.signal_label:<13}{s.city:<22}{s.state:<7}{s.format:<24}{s.school}")


def main():
	parser = argparse.ArgumentParser(description="Look up radio stations on radio-locator.com.")
	parser.add_argument("zip_code", nargs="?", help="list stations near this 5 digit zip code")
	parser.add_argument("--info", metavar="CALL_SIGN", help="show full details for one station, such as KTUI or KTUI-AM")
	args = parser.parse_args()
	if args.info:
		show_info(args.info)
	else:
		show_search(args.zip_code or input("Zip code: "))


if __name__ == "__main__":
	main()
