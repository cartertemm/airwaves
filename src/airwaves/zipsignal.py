import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

SECTION_PATTERN = re.compile(r"<h1>(AM|FM) Stations Covering.*?</h1>(.*?)</table>", re.S)
ROW_PATTERN = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_PATTERN = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_PATTERN = re.compile(r"<[^>]+>")
ZIP_PATTERN = re.compile(r"\d{5}")
CELLS_PER_ROW = 6
BAND_UNITS = (("FM", "MHz"), ("AM", "kHz"))


@dataclass
class Station:
	band: str
	field_strength: float
	call_sign: str
	city: str
	state: str
	frequency: float
	facility_id: int


class ZipSignal:
	URL = "https://zipsignal.v-soft.com/"
	HEADERS = {
		"Content-Type": "application/x-www-form-urlencoded",
		"Origin": "https://www.v-soft.com",
		"Referer": "https://www.v-soft.com/",
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
	}

	def fetch(self, zip_code):
		return self.parse(self.fetch_html(zip_code))

	def fetch_html(self, zip_code):
		data = urllib.parse.urlencode({"zip": zip_code, "Submit": "Find Stations"}).encode()
		request = urllib.request.Request(self.URL, data=data, headers=self.HEADERS)
		with urllib.request.urlopen(request) as response:
			return response.read().decode("iso-8859-1")

	@staticmethod
	def parse(html):
		stations = []
		for band, table in SECTION_PATTERN.findall(html):
			for row in ROW_PATTERN.findall(table):
				cells = [TAG_PATTERN.sub("", cell).strip() for cell in CELL_PATTERN.findall(row)]
				if len(cells) != CELLS_PER_ROW:
					continue
				field_strength, call_sign, city, state, frequency, facility_id = cells
				try:
					stations.append(Station(band, float(field_strength), call_sign, city, state, float(frequency), int(facility_id)))
				except ValueError:
					continue
		return stations


def main():
	zip_code = sys.argv[1] if len(sys.argv) > 1 else input("Zip code: ")
	zip_code = zip_code.strip()
	if not ZIP_PATTERN.fullmatch(zip_code):
		print("Enter a 5 digit zip code.")
		return
	stations = ZipSignal().fetch(zip_code)
	if not stations:
		print("No stations found.")
		return
	for band, unit in BAND_UNITS:
		band_stations = sorted((s for s in stations if s.band == band), key=lambda s: s.frequency)
		print(f"\n{band} ({unit}): {len(band_stations)} found")
		for station in band_stations:
			print(f"{station.frequency:g}\t{station.call_sign}")


if __name__ == "__main__":
	main()
