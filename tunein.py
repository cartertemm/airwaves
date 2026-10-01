import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields

API_URL = "https://opml.radiotime.com/{}.ashx?"
GEOCODE_URL = "https://nominatim.openstreetmap.org/search?"
GEOCODE_HEADERS = {"User-Agent": "radio-utils/1.0"}
HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}
STREAM_FORMATS = "mp3,aac,ogg,hls,flash,wma"
MAX_WORKERS = 6
ZIP_PATTERN = re.compile(r"\d{5}")


def from_dict(cls, data, **overrides):
	names = {f.name for f in fields(cls)}
	values = {key.lower(): value for key, value in data.items()}
	return cls(**{key: value for key, value in values.items() if key in names}, **overrides)


@dataclass
class Listing:
	guide_id: str
	element: str | None = None
	type: str | None = None
	item: str | None = None
	text: str | None = None
	subtext: str | None = None
	url: str | None = None
	image: str | None = None
	bitrate: str | None = None
	reliability: str | None = None
	formats: str | None = None
	genre_id: str | None = None
	now_playing_id: str | None = None
	preset_id: str | None = None
	show_id: str | None = None
	current_track: str | None = None
	playing: str | None = None
	playing_image: str | None = None


@dataclass
class Stream:
	url: str
	element: str | None = None
	guide_id: str | None = None
	media_type: str | None = None
	bitrate: int | None = None
	reliability: int | None = None
	position: int | None = None
	player_width: int | None = None
	player_height: int | None = None
	is_direct: bool | None = None
	is_hls_advanced: str | None = None
	live_seek_stream: str | None = None
	is_ad_clipped_content_enabled: str | None = None
	playlist_type: str | None = None
	use_stream_metadata: str | None = None


@dataclass
class Station:
	guide_id: str
	element: str | None = None
	preset_id: str | None = None
	name: str | None = None
	call_sign: str | None = None
	slogan: str | None = None
	frequency: str | None = None
	band: str | None = None
	url: str | None = None
	report_url: str | None = None
	detail_url: str | None = None
	tunein_url: str | None = None
	logo: str | None = None
	description: str | None = None
	location: str | None = None
	language: str | None = None
	genre_id: str | None = None
	genre_name: str | None = None
	region_id: str | None = None
	country_region_id: int | None = None
	latlon: str | None = None
	tz: str | None = None
	tz_offset: str | None = None
	email: str | None = None
	phone: str | None = None
	mailing_address: str | None = None
	twitter_id: str | None = None
	is_preset: bool | None = None
	is_available: bool | None = None
	is_music: bool | None = None
	is_family_content: bool | None = None
	is_mature_content: bool | None = None
	is_event: bool | None = None
	content_classification: str | None = None
	has_song: bool | None = None
	has_schedule: bool | None = None
	has_topics: bool | None = None
	has_profile: str | None = None
	current_song: str | None = None
	current_artist: str | None = None
	current_artist_id: str | None = None
	current_album: str | None = None
	current_artist_art: str | None = None
	current_album_art: str | None = None
	now_playing_url: str | None = None
	nowplaying_channel: str | None = None
	publish_song: bool | None = None
	publish_song_url: str | None = None
	publish_song_rejection_reason: str | None = None
	external_key: str | None = None
	ad_eligible: bool | None = None
	preroll_ad_eligible: bool | None = None
	companion_ad_eligible: bool | None = None
	video_preroll_ad_eligible: bool | None = None
	why_ads_text: str | None = None
	fb_share: bool | None = None
	twitter_share: bool | None = None
	song_share: bool | None = None
	song_buy_eligible: bool | None = None
	donation_eligible: str | None = None
	donation_url: str | None = None
	donation_text: str | None = None
	donation_icon: str | None = None
	favorited_count: int | None = None
	is_favorited: bool | None = None
	is_favoritable: bool | None = None
	can_cast: bool | None = None
	nielsen_eligible: bool | None = None
	nielsen_provider: str | None = None
	nielsen_asset_id: str | None = None
	use_native_player: bool | None = None
	live_seek_stream: bool | None = None
	seek_disabled: bool | None = None
	streams: list[Stream] = field(default_factory=list)
	listing: Listing | None = None


@dataclass
class Place:
	name: str
	lat: str
	lon: str


class TuneIn:
	def __init__(self, max_workers=MAX_WORKERS):
		self.max_workers = max_workers

	@staticmethod
	def fetch_json(url, headers=HEADERS):
		with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as response:
			return json.load(response)

	def fetch_body(self, method, **params):
		return self.fetch_json(API_URL.format(method) + urllib.parse.urlencode({"render": "json", **params})).get("body", [])

	def get_streams(self, guide_id):
		return [from_dict(Stream, audio) for audio in self.fetch_body("Tune", id=guide_id, formats=STREAM_FORMATS) if audio.get("element") == "audio"]

	def get_station(self, guide_id, listing=None):
		streams = self.get_streams(guide_id)
		details = self.fetch_body("Describe", id=guide_id)
		if details:
			return from_dict(Station, details[0], streams=streams, listing=listing)
		return Station(guide_id, name=listing and listing.text, slogan=listing and listing.subtext, streams=streams, listing=listing)

	def get_stations(self, results):
		listings = [from_dict(Listing, result) for result in results if result.get("item") == "station"]
		with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
			return list(pool.map(lambda listing: self.get_station(listing.guide_id, listing), listings))

	def search(self, query):
		return self.get_stations(self.fetch_body("Search", query=query))

	def search_callsign(self, callsign):
		callsign = callsign.upper()
		return [station for station in self.search(callsign) if (station.call_sign or "").upper().split("-")[0] == callsign]

	def locate(self, location):
		params = {"postalcode": location, "countrycodes": "us"} if ZIP_PATTERN.fullmatch(location) else {"q": location}
		places = self.fetch_json(GEOCODE_URL + urllib.parse.urlencode({**params, "format": "json", "limit": 1}), GEOCODE_HEADERS)
		return Place(places[0]["display_name"], places[0]["lat"], places[0]["lon"]) if places else None

	def stations_near(self, place):
		groups = self.fetch_body("Browse", c="local", latlon=f"{place.lat},{place.lon}")
		return self.get_stations(result for group in groups for result in group.get("children", []))


def print_station(station):
	print(f"\n{station.name} ({station.guide_id})")
	if station.slogan:
		print(station.slogan)
	print(f"{station.call_sign or ''} {station.frequency or ''} {station.band or ''}".strip())
	for label, value in (("Location", station.location), ("Genre", station.genre_name), ("Language", station.language), ("Website", station.url)):
		if value:
			print(f"{label}: {value}")
	if not station.streams:
		print("No streams")
	for stream in station.streams:
		print(f"{stream.media_type} {stream.bitrate}k: {stream.url}")


def main():
	sys.stdout.reconfigure(encoding="utf-8")
	parser = argparse.ArgumentParser(description="Find TuneIn stations and their stream URLs.")
	group = parser.add_mutually_exclusive_group()
	group.add_argument("query", nargs="?", help="search station names")
	group.add_argument("--location", help="list stations near a place, for example \"Phoenix, AZ\" or a zip code")
	group.add_argument("--callsign", help="find stations with this call sign, for example KJZZ")
	args = parser.parse_args()
	tunein = TuneIn()
	if args.location:
		place = tunein.locate(args.location.strip())
		if not place:
			print("Location not found.")
			return
		print(f"Stations near {place.name}")
		stations = tunein.stations_near(place)
	elif args.callsign:
		stations = tunein.search_callsign(args.callsign.strip())
	else:
		stations = tunein.search((args.query or input("Search: ")).strip())
	if not stations:
		print("No stations found.")
		return
	for station in stations:
		print_station(station)


if __name__ == "__main__":
	main()
