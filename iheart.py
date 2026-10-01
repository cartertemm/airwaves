import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SEARCH_URL = "https://us.api.iheart.com/api/v3/search/all?"
STATION_URL = "https://us.api.iheart.com/api/v2/content/liveStations/{}"
HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}
MAX_RESULTS = 1000
MAX_WORKERS = 6
SEARCH_TYPES = ("bundle", "station", "artist", "track", "playlist", "podcast")


def fetch_json(url):
	with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as response:
		return json.load(response)


def search_stations(query, max_results=MAX_RESULTS):
	params = {"keywords": query, "maxRows": max_results}
	params.update({kind: str(kind == "station").lower() for kind in SEARCH_TYPES})
	results = fetch_json(SEARCH_URL + urllib.parse.urlencode(params)).get("results", {}).get("stations", [])
	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
		return list(pool.map(lambda result: fetch_json(STATION_URL.format(result["id"]))["hits"][0], results))


def print_station(station):
	print(f"\n{station['name']} ({station['id']})")
	if station.get("description"):
		print(station["description"])
	print(f"{station.get('callLetters', '')} {station.get('freq', '')} {station.get('band', '')}".strip())
	markets = ", ".join(f"{m['city']}, {m['stateAbbreviation']}" for m in station.get("markets", []))
	genres = ", ".join(g["name"] for g in station.get("genres", []))
	for label, value in (("Market", markets), ("Genre", genres), ("Website", station.get("website"))):
		if value:
			print(f"{label}: {value}")
	streams = station.get("streams", {})
	if not streams:
		print("No streams")
	for name, url in streams.items():
		print(f"{name}: {url}")


def main():
	query = sys.argv[1] if len(sys.argv) > 1 else input("Search: ")
	stations = search_stations(query.strip())
	if not stations:
		print("No stations found.")
		return
	for station in stations:
		print_station(station)


if __name__ == "__main__":
	main()
