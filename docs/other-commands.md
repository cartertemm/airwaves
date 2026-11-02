# Other commands

These commands are unsupported for now. They depend on outside websites that can change without notice, so they may stop working, and bugs in them may not be fixed.

These commands use only the standard library. If you run one with no arguments, it asks you for input.

Some of these services (radio-locator.com, for example) limit how many requests one IP address can make. Not all of the limits are documented.

| Command | Source | Purpose |
| --- | --- | --- |
| `radio-locator` | radio-locator.com | Lists AM and FM stations near a zip code with distance, signal strength, and format. Shows full details for one call sign. |
| `zipsignal` | V-Soft ZipSignal | Lists AM and FM stations whose signal covers a zip code. |
| `tunein` | TuneIn | Searches stations by name, call sign, or location and prints their stream URLs. |
| `iheart` | iHeartRadio | Searches iHeartRadio stations and prints their stream URLs. |
| `streema` | Streema | Prints the direct stream URL for a call sign. |
| `broadcastify` | Broadcastify | Searches scanner feeds (fire, police, weather, and more) and prints their stream URLs. |

## Finding stations at a location

You can use `radio-locator`, `zipsignal`, or `tunein`.

`radio-locator` and `zipsignal` take a 5 digit US zip code:

```
uv run radio-locator 60601
uv run zipsignal 60601
```

To get full details for one station from the list, such as its owner, address, and transmitter data:

```
uv run radio-locator --info WBBM
uv run radio-locator --info WGN-AM
```

`tunein` takes a place name or a zip code and also prints the stream URLs:

```
uv run tunein --location "Chicago, IL"
uv run tunein --location 60601
```

## Finding the direct stream URL from a call sign

You can use `streema`, `tunein`, or `iheart`.

```
uv run streema WFMT
uv run streema WGN-AM
uv run tunein --callsign WFMT
```

`tunein` and `iheart` can also search by station name:

```
uv run tunein "jazz"
uv run iheart WGCI
```

## Finding fire, police, weather, etc

You can use `broadcastify`.

Search feeds by place or keyword. The results show the feed ID, status, and listener count:

```
uv run broadcastify "Cook County"
uv run broadcastify "NOAA weather"
```

Then get the stream URL with the feed ID or the feed name:

```
uv run broadcastify --stream 20973
```
