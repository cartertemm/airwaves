import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields

SEARCH_URL = "https://us.api.iheart.com/api/v3/search/all?"
STATION_URL = "https://us.api.iheart.com/api/v2/content/liveStations/{}"
HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}
MAX_RESULTS = 1000
MAX_WORKERS = 6
SEARCH_TYPES = ("bundle", "station", "artist", "track", "playlist", "podcast")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake_case(name):
	return CAMEL_BOUNDARY.sub("_", name).replace("-", "_").lower()


def from_dict(cls, data, **overrides):
	names = {f.name for f in fields(cls)}
	values = {snake_case(key): value for key, value in (data or {}).items()}
	return cls(**{key: value for key, value in values.items() if key in names}, **overrides)


@dataclass
class SearchResult:
	id: int
	name: str | None = None
	description: str | None = None
	call_letters: str | None = None
	frequency: str | None = None
	image_url: str | None = None
	score: float | None = None
	norm_rank: float | None = None
	genre: str | None = None
	streaming_platform: str | None = None
	talkback_enabled: bool | None = None


@dataclass
class Streams:
	hls_stream: str | None = None
	secure_hls_stream: str | None = None
	shoutcast_stream: str | None = None
	secure_shoutcast_stream: str | None = None
	pls_stream: str | None = None
	secure_pls_stream: str | None = None


@dataclass
class Market:
	type: str | None = None
	name: str | None = None
	market_id: str | None = None
	sort_index: int | None = None
	city: str | None = None
	state_id: int | None = None
	state_abbreviation: str | None = None
	city_id: int | None = None
	country: str | None = None
	country_id: int | None = None
	origin: bool | None = None
	primary: bool | None = None


@dataclass
class Genre:
	type: str | None = None
	id: int | None = None
	name: str | None = None
	sort_index: int | None = None
	primary: bool | None = None


@dataclass
class Pronouncement:
	utterance: str | None = None
	primary: bool | None = None


@dataclass
class Feeds:
	child_oriented: str | None = None
	enable_triton_tracking: str | None = None
	feed: str | None = None
	sponsored: str | None = None


@dataclass
class Social:
	facebook: str | None = None
	twitter: str | None = None
	instagram: str | None = None
	snapchat: str | None = None
	tiktok: str | None = None
	youtube: str | None = None
	threads: str | None = None


@dataclass
class Adswizz:
	adswizz_host: str | None = None
	enable_adswizz_targeting: str | None = None
	publisher_id: str | None = None


@dataclass
class AdswizzZones:
	audio_exchange_zone: str | None = None
	optimized_audio_fill_zone: str | None = None
	audio_fill_zone: str | None = None
	audio_zone: str | None = None
	display_zone: str | None = None


@dataclass
class Ads:
	audio_ad_provider: str | None = None
	enable_triton_token: str | None = None
	provider_id: str | None = None


@dataclass
class Station:
	id: int
	name: str | None = None
	description: str | None = None
	call_letters: str | None = None
	freq: str | None = None
	band: str | None = None
	logo: str | None = None
	website: str | None = None
	link: str | None = None
	phone: str | None = None
	email: str | None = None
	format: str | None = None
	countries: str | None = None
	score: float | None = None
	response_type: str | None = None
	cume: int | None = None
	is_active: bool | None = None
	modified: str | None = None
	esid: str | None = None
	provider: str | None = None
	rds: str | None = None
	rds_pi_code: str | None = None
	call_letter_alias: str | None = None
	call_letter_royalty: str | None = None
	fcc_facility_id: str | None = None
	streaming_platform: str | None = None
	talkback_enabled: bool | None = None
	streams: Streams = field(default_factory=Streams)
	markets: list[Market] = field(default_factory=list)
	genres: list[Genre] = field(default_factory=list)
	pronouncements: list[Pronouncement] = field(default_factory=list)
	feeds: Feeds = field(default_factory=Feeds)
	social: Social = field(default_factory=Social)
	adswizz: Adswizz = field(default_factory=Adswizz)
	adswizz_zones: AdswizzZones = field(default_factory=AdswizzZones)
	ads: Ads = field(default_factory=Ads)
	search_result: SearchResult | None = None

	@classmethod
	def from_dict(cls, data, search_result=None):
		return from_dict(
			cls,
			{key: value for key, value in data.items() if not isinstance(value, (dict, list))},
			streams=from_dict(Streams, data.get("streams")),
			markets=[from_dict(Market, market) for market in data.get("markets", [])],
			genres=[from_dict(Genre, genre) for genre in data.get("genres", [])],
			pronouncements=[from_dict(Pronouncement, item) for item in data.get("pronouncements", [])],
			feeds=from_dict(Feeds, data.get("feeds")),
			social=from_dict(Social, data.get("social")),
			adswizz=from_dict(Adswizz, data.get("adswizz")),
			adswizz_zones=from_dict(AdswizzZones, data.get("adswizzZones")),
			ads=from_dict(Ads, data.get("ads")),
			search_result=search_result,
		)


class IHeartRadio:
	def __init__(self, max_workers=MAX_WORKERS):
		self.max_workers = max_workers

	@staticmethod
	def fetch_json(url):
		with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as response:
			return json.load(response)

	def get_station(self, station_id, search_result=None):
		return Station.from_dict(self.fetch_json(STATION_URL.format(station_id))["hits"][0], search_result)

	def search(self, query, max_results=MAX_RESULTS):
		params = {"keywords": query, "maxRows": max_results}
		params.update({kind: str(kind == "station").lower() for kind in SEARCH_TYPES})
		results = self.fetch_json(SEARCH_URL + urllib.parse.urlencode(params)).get("results", {}).get("stations", [])
		results = [from_dict(SearchResult, result) for result in results]
		with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
			return list(pool.map(lambda result: self.get_station(result.id, result), results))


def print_station(station):
	print(f"\n{station.name} ({station.id})")
	if station.description:
		print(station.description)
	print(f"{station.call_letters or ''} {station.freq or ''} {station.band or ''}".strip())
	markets = ", ".join(f"{market.city}, {market.state_abbreviation}" for market in station.markets)
	genres = ", ".join(genre.name for genre in station.genres)
	for label, value in (("Market", markets), ("Genre", genres), ("Website", station.website)):
		if value:
			print(f"{label}: {value}")
	streams = {name: url for name, url in vars(station.streams).items() if url}
	if not streams:
		print("No streams")
	for name, url in streams.items():
		print(f"{name}: {url}")


def main():
	query = sys.argv[1] if len(sys.argv) > 1 else input("Search: ")
	stations = IHeartRadio().search(query.strip())
	if not stations:
		print("No stations found.")
		return
	for station in stations:
		print_station(station)


if __name__ == "__main__":
	main()
