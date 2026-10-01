import base64
import html
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib

PLAY_URL = "http://p.radios.streema.com/radios/play/"
SEARCH_URL = "https://streema.com/radios/search/?q="
HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}
BANDS = ("FM", "AM")
SEARCH_ITEM_MARKER = 'data-role="player-popup"'
SLUG_PATTERN = re.compile(r'data-url="/radios/play/([^"]+)"')
TITLE_PATTERN = re.compile(r'title="Play ([^"]*)"')
BAND_DIAL_PATTERN = re.compile(r'class="band-dial">\s*([^<]*)<')
ENCODED_STREAM_PATTERN = re.compile(r"id=\"source-stream\"[^>]*data-src='([^']*)'")
RADIO_BAND_PATTERN = re.compile(r'data-radio-band="([^"]*)"')


def get_stream_url(call_sign):
	def fetch(url):
		try:
			with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as response:
				return response.read().decode("utf-8", errors="replace")
		except urllib.error.HTTPError:
			return ""

	def stream_from(slugs):
		for slug in slugs:
			page = fetch(PLAY_URL + urllib.parse.quote(slug))
			encoded = ENCODED_STREAM_PATTERN.search(page)
			radio_band = RADIO_BAND_PATTERN.search(page)
			if encoded and encoded.group(1) and not (band and radio_band and radio_band.group(1) != band):
				return zlib.decompress(base64.b64decode(encoded.group(1))).decode()
		return None

	call_sign = call_sign.strip().upper()
	base, _, band = call_sign.partition("-")
	if band not in BANDS:
		base, band = call_sign, ""
	direct_slugs = [f"{base}_{band}", base] if band else [base] + [f"{base}_{b}" for b in BANDS]
	url = stream_from(direct_slugs)
	if url:
		return url
	call_word = re.compile(rf"(?<![\w-]){re.escape(base)}(?:-(?:AM|FM))?(?![\w-])", re.I)
	search_slugs = []
	for item in fetch(SEARCH_URL + urllib.parse.quote(base)).split(SEARCH_ITEM_MARKER)[1:]:
		slug, title, dial = SLUG_PATTERN.search(item), TITLE_PATTERN.search(item), BAND_DIAL_PATTERN.search(item)
		if slug and title and call_word.search(html.unescape(title.group(1))) and (not band or (dial and dial.group(1).startswith(band))):
			search_slugs.append(slug.group(1))
	return stream_from(slug for slug in dict.fromkeys(search_slugs) if slug not in direct_slugs)


if __name__ == "__main__":
	print(get_stream_url(sys.argv[1] if len(sys.argv) > 1 else input("Call sign: ")))
