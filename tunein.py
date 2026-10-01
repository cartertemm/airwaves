import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://opml.radiotime.com/{}.ashx?"
HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}
STREAM_FORMATS = "mp3,aac,ogg,hls,flash,wma"
MAX_WORKERS = 6


def fetch_body(method, **params):
	url = API_URL.format(method) + urllib.parse.urlencode({"render": "json", **params})
	with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as response:
		return json.load(response).get("body", [])


def fetch_station(result):
	details = fetch_body("Describe", id=result["guide_id"])
	station = details[0] if details else {"guide_id": result["guide_id"], "name": result["text"], "slogan": result.get("subtext")}
	station["streams"] = [audio for audio in fetch_body("Tune", id=result["guide_id"], formats=STREAM_FORMATS) if audio.get("element") == "audio"]
	return station


def search_stations(query):
	results = [result for result in fetch_body("Search", query=query) if result.get("item") == "station"]
	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
		return list(pool.map(fetch_station, results))


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
	query = sys.argv[1] if len(sys.argv) > 1 else input("Search: ")
	stations = search_stations(query.strip())
	if not stations:
		print("No stations found.")
		return
	for station in stations:
		print_station(station)


if __name__ == "__main__":
	main()
