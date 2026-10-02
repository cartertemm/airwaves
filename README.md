# Radio Utils

A set of CLI based utilities having to do with discovering nearby radio stations, finding their stream URLs, and ultimately playing them.

These were mostly written a few years ago (before the GenAI era). I have continued maintaining them because I have found them useful. I hope someone else does so too!

Please note that some of these services (radio locator for instance) impose IP-based rate limits. Not all of them are documented. It is important to do your own A/B testing and be mindful of this so you don't encounter them in an application.

All scripts need Python 3.10 or later. All scripts except `fmradio.py` use only the standard library.

Here is a list of the available scripts:

| Script | Source | Purpose |
| --- | --- | --- |
| `radiolocator.py` | radio-locator.com | Lists AM and FM stations near a zip code with distance, signal strength, and format. Shows full details for one call sign. |
| `zipsignal.py` | V-Soft ZipSignal | Lists AM and FM stations whose signal covers a zip code. |
| `tunein.py` | TuneIn | Searches stations by name, call sign, or location and prints their stream URLs. |
| `iheart.py` | iHeartRadio | Searches iHeartRadio stations and prints their stream URLs. |
| `streema.py` | Streema | Prints the direct stream URL for a call sign. |
| `broadcastify.py` | Broadcastify | Searches scanner feeds (fire, police, weather, and more) and prints their stream URLs. |
| `fmradio.py` | RTL-SDR dongle | Plays FM stereo radio and NOAA weather radio from an RTL-SDR USB dongle. |

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

## Listening to FM or weather radio with an RTL-SDR dongle

You can use `fmradio.py`. It needs some packages:

```
pip install numpy scipy pyaudio pyrtlsdr pyrtlsdrlib
```

Give a frequency in MHz, or give no frequency to start at 87.5 MHz:

```
python fmradio.py 97.9
python fmradio.py
```

NOAA weather radio works the same way. Give a channel from 162.400 to 162.550 MHz:

```
python fmradio.py 162.55
```

If you have more than one dongle, the script asks you to choose one.

| Key | Action |
| --- | --- |
| Space | Play or pause |
| `_` | Volume down |
| `+` | Volume up |
| `s` | Go back one step (0.1 MHz on FM, 25 kHz on weather radio) |
| `w` | Go forward one step |
| `t` | Type a frequency in MHz |
| `m` | Mute or unmute |
| Ctrl+C | Quit |

The keys work on Windows only.

### Using the receiver from another program

`fmradio.py` can also be imported. The receiver does not need the keyboard controls:

```python
import fmradio

devices = fmradio.list_devices()
receiver = fmradio.Receiver(devices[0].index, 97.9)
receiver.on_stereo_change = lambda stereo: print("Stereo" if stereo else "Mono")
receiver.start()
receiver.volume = 70
receiver.tune(98.7)
receiver.muted = True
receiver.paused = True
receiver.stop()
```

| Member | Purpose |
| --- | --- |
| `list_devices()` | Returns the connected dongles, each with `index`, `name`, and `serial`. |
| `start()`, `stop()` | Start and stop the dongle and audio. |
| `tune(freq_mhz)`, `freq_mhz` | Change and read the frequency. FM and NOAA frequencies both work. Other frequencies raise `ValueError`. |
| `band` | The current band, `fmradio.FM` or `fmradio.NOAA`. |
| `volume` | Volume from 0 to 100. |
| `paused`, `muted` | Pause or mute the audio. |
| `stereo` | True when the station sends stereo. |
| `on_stereo_change` | Called with the new stereo state. It runs on a background thread. |
| `running`, `error` | `running` becomes false if the dongle fails, and `error` holds the cause. |
