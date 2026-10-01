# Radio Utils

A set of CLI based utilities having to do with discovering nearby radio stations, finding their stream URLs, and ultimately playing them.

These were mostly written a few years ago (before the GenAI era). I have continued maintaining them because I have found them useful. I hope someone else does so too!

All scripts need Python 3.10 or later and use only the standard library. There is nothing to install.

Here is a list of the available scripts:

| Script | Source | What it does |
| --- | --- | --- |
| `radiolocator.py` | radio-locator.com | Lists AM and FM stations near a zip code with distance, signal strength, and format. Shows full details for one call sign. |
| `zipsignal.py` | V-Soft ZipSignal | Lists AM and FM stations whose signal covers a zip code. |
| `tunein.py` | TuneIn | Searches stations by name, call sign, or location and prints their stream URLs. |
| `iheart.py` | iHeartRadio | Searches iHeartRadio stations and prints their stream URLs. |
| `streema.py` | Streema | Prints the direct stream URL for a call sign. |
| `broadcastify.py` | Broadcastify | Searches scanner feeds (fire, police, weather, and more) and prints their stream URLs. |

If you run a script with no arguments, it asks you for input.

## Finding stations at a location

You can use `radiolocator.py`, `zipsignal.py`, or `tunein.py`.

`radiolocator.py` and `zipsignal.py` take a 5 digit US zip code:

```
python radiolocator.py 60601
python zipsignal.py 60601
```

To get full details for one station from the list, such as its owner, address, and transmitter data:

```
python radiolocator.py --info WBBM
python radiolocator.py --info WGN-AM
```

`tunein.py` takes a place name or a zip code and also prints the stream URLs:

```
python tunein.py --location "Chicago, IL"
python tunein.py --location 60601
```

## Finding the direct stream URL from a call sign

You can use `streema.py`, `tunein.py`, or `iheart.py`.

```
python streema.py WFMT
python streema.py WGN-AM
python tunein.py --callsign WFMT
```

`tunein.py` and `iheart.py` can also search by station name:

```
python tunein.py "jazz"
python iheart.py WGCI
```

## Finding fire, police, weather, etc

You can use `broadcastify.py`.

Search feeds by place or keyword. The results show the feed ID, status, and listener count:

```
python broadcastify.py "Cook County"
python broadcastify.py "NOAA weather"
```

Then get the stream URL with the feed ID or the feed name:

```
python broadcastify.py --stream 20973
```
