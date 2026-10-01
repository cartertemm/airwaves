import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://opml.radiotime.com/{}.ashx?"
GEOCODE_URL = "https://nominatim.openstreetmap.org/search?"
GEOCODE_HEADERS = {"User-Agent": "radio-utils/1.0"}
HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}
STREAM_FORMATS = "mp3,aac,ogg,hls,flash,wma"
MAX_WORKERS = 6
ZIP_PATTERN = re.compile(r"\d{5}")


def fetch_json(url, headers=HEADERS):
	with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as response:
		return json.load(response)


def fetch_body(method, **params):
	return fetch_json(API_URL.format(method) + urllib.parse.urlencode({"render": "json", **params})).get("body", [])


def fetch_station(result):
	details = fetch_body("Describe", id=result["guide_id"])
	station = details[0] if details else {"guide_id": result["guide_id"], "name": result["text"], "slogan": result.get("subtext")}
	station["streams"] = [audio for audio in fetch_body("Tune", id=result["guide_id"], formats=STREAM_FORMATS) if audio.get("element") == "audio"]
	return station


def fetch_stations(results):
	results = [result for result in results if result.get("item") == "station"]
	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
		return list(pool.map(fetch_station, results))


def search_stations(query):
	return fetch_stations(fetch_body("Search", query=query))


def callsign_stations(callsign):
	callsign = callsign.upper()
	return [station for station in search_stations(callsign) if (station.get("call_sign") or "").upper().split("-")[0] == callsign]


def location_stations(location):
	params = {"postalcode": location, "countrycodes": "us"} if ZIP_PATTERN.fullmatch(location) else {"q": location}
	places = fetch_json(GEOCODE_URL + urllib.parse.urlencode({**params, "format": "json", "limit": 1}), GEOCODE_HEADERS)
	if not places:
		print("Location not found.")
		return []
	print(f"Stations near {places[0]['display_name']}")
	groups = fetch_body("Browse", c="local", latlon=f"{places[0]['lat']},{places[0]['lon']}")
	return fetch_stations(result for group in groups for result in group.get("children", []))


def print_station(station):
	print(f"\n{station['name']} ({station['guide_id']})")
	if station.get("slogan"):
		print(station["slogan"])
	print(f"{station.get('call_sign') or ''} {station.get('frequency') or ''} {station.get('band') or ''}".strip())
	for label, key in (("Location", "location"), ("Genre", "genre_name"), ("Language", "language"), ("Website", "url")):
		if station.get(key):
			print(f"{label}: {station[key]}")
	if not station["streams"]:
		print("No streams")
	for stream in station["streams"]:
		print(f"{stream.get('media_type')} {stream.get('bitrate')}k: {stream['url']}")


def main():
	sys.stdout.reconfigure(encoding="utf-8")
	parser = argparse.ArgumentParser(description="Find TuneIn stations and their stream URLs.")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("query", nargs="?", help="search station names")
	group.add_argument("--location", help="list stations near a place, for example \"Phoenix, AZ\" or a zip code")
	group.add_argument("--callsign", help="find stations with this call sign, for example KJZZ")
	args = parser.parse_args()
	if args.location:
		stations = location_stations(args.location.strip())
	elif args.callsign:
		stations = callsign_stations(args.callsign.strip())
	else:
		stations = search_stations((args.query or input("Search: ")).strip())
	if not stations:
		print("No stations found.")
		return
	for station in stations:
		print_station(station)


if __name__ == "__main__":
	main()
