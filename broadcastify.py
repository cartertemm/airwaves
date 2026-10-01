import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
TABLE_PATTERN = re.compile(r'<table class="[^"]*listen-feed-table[^"]*"[^>]*>(.*?)</table>', re.S)
ROW_PATTERN = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_PATTERN = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
ONLINE_MARKER = 'title="Online"'
FEED_LINK_PATTERN = re.compile(r'<a href="/listen/feed/(\d+)">(.*?)</a>', re.S)
DESCRIPTION_PATTERN = re.compile(r'<span class="text-muted"[^>]*>(.*?)</span>', re.S)
ALPHA_TAGS_MARKER = "Alpha Tags Available"
HLS_URL_PATTERN = re.compile(r'hlsUrl:\s*"([^"]*)"')
RELAY_URL_PATTERN = re.compile(r'relayUrl:\s*"([^"]*)"')
ONLINE_PATTERN = re.compile(r"isOnline:\s*(true|false)")
CELLS_PER_ROW = 5


def clean(fragment):
	text = html.unescape(TAG_PATTERN.sub(" ", fragment)).replace("\xa0", " ")
	return SPACE_PATTERN.sub(" ", text).replace(" ,", ",").strip()


@dataclass
class Feed:
	feed_id: int
	name: str
	description: str
	location: str
	genre: str
	listeners: int
	online: bool
	has_alpha_tags: bool


class Broadcastify:
	BASE_URL = "https://www.broadcastify.com"
	HEADERS = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
	}

	def get(self, path):
		request = urllib.request.Request(self.BASE_URL + path, headers=self.HEADERS)
		with urllib.request.urlopen(request) as response:
			return response.read().decode("utf-8", errors="replace")

	def search(self, query):
		return self.parse_search(self.get("/listen/?" + urllib.parse.urlencode({"q": query})))

	def stream_url(self, feed):
		feed_id = feed if str(feed).isdigit() else self.find_feed_id(feed)
		if feed_id is None:
			return None
		page = self.get(f"/listen/feed/{feed_id}")
		online = ONLINE_PATTERN.search(page)
		if not online or online.group(1) != "true":
			return None
		for pattern in (HLS_URL_PATTERN, RELAY_URL_PATTERN):
			match = pattern.search(page)
			if match and match.group(1):
				return json.loads(f'"{match.group(1)}"')
		return None

	def find_feed_id(self, name):
		feeds = self.search(name)
		exact = [feed for feed in feeds if feed.name.casefold() == name.strip().casefold()]
		best = max(exact or feeds, key=lambda feed: feed.listeners, default=None)
		return best.feed_id if best else None

	@staticmethod
	def parse_search(page):
		table = TABLE_PATTERN.search(page)
		if not table:
			return []
		feeds = []
		for row in ROW_PATTERN.findall(table.group(1)):
			cells = CELL_PATTERN.findall(row)
			link = FEED_LINK_PATTERN.search(row)
			if len(cells) != CELLS_PER_ROW or not link:
				continue
			status, location, feed_cell, genre, listeners = cells
			description = DESCRIPTION_PATTERN.search(feed_cell)
			feeds.append(Feed(
				feed_id=int(link.group(1)),
				name=clean(link.group(2)),
				description=clean(description.group(1)) if description else "",
				location=clean(location),
				genre=clean(genre),
				listeners=int(clean(listeners).replace(",", "") or 0),
				online=ONLINE_MARKER in status,
				has_alpha_tags=ALPHA_TAGS_MARKER in feed_cell,
			))
		return feeds


def show_search(query):
	feeds = sorted(Broadcastify().search(query), key=lambda feed: feed.listeners, reverse=True)
	if not feeds:
		print("No feeds found.")
		return
	print(f"{len(feeds)} feeds found for {query!r}\n")
	print(f"{'ID':<8}{'Status':<9}{'Listeners':<11}{'Genre':<18}{'Location':<22}Name")
	for feed in feeds:
		status = "online" if feed.online else "offline"
		print(f"{feed.feed_id:<8}{status:<9}{feed.listeners:<11}{feed.genre:<18}{feed.location:<22}{feed.name}")


def show_stream(feed):
	url = Broadcastify().stream_url(feed)
	print(url or f"No online stream found for {feed}.")


def main():
	parser = argparse.ArgumentParser(description="Search Broadcastify feeds and get their stream URLs.")
	parser.add_argument("query", nargs="?", help="search feeds by name, place or keyword")
	parser.add_argument("--stream", metavar="ID_OR_NAME", help="print the stream URL for a feed id or feed name")
	args = parser.parse_args()
	if args.stream:
		show_stream(args.stream)
	else:
		show_search(args.query or input("Search: "))


if __name__ == "__main__":
	main()
