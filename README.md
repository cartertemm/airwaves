# Radio Utils

This repository contains scripts for digitally receiving and getting information about radio stations.

The primary application is `sdr.py`, a radio receiver that plays AM, shortwave, FM, aviation, and NOAA weather radio from an RTL-SDR USB dongle. The other scripts find nearby stations and their stream URLs through online services such as TuneIn and Broadcastify.

## SDR Listener

### Features

* AM radio from 0.53 to 1.7 MHz.
* Shortwave radio from 2.3 to 14.4 MHz, in 5 kHz channels.
* FM radio in stereo, with the station name and radio text (often the artist and song) from RDS.
* The aviation band from 118.000 to 136.975 MHz, in 25 kHz channels. Aircraft and control towers only transmit when someone talks, so you hear static between transmissions.
* NOAA weather radio from 162.400 to 162.550 MHz, with weather alerts. The script reads the alert codes (SAME) that stations send before each alert, and the 1050 Hz alarm tone.
* Scanning up or down to the next station in the band.
* US and European band settings. In Europe, AM is 531 to 1602 kHz in 9 kHz steps, FM uses 50 microsecond de-emphasis, and there is no NOAA weather radio.
* The status line and the window title show the frequency, and optionally the signal strength.
* Casting to Sonos speakers, with the station and song shown in the Sonos app.

AM and shortwave use the dongle's direct sampling mode. Some dongles need a hardware change before direct sampling picks up anything. Direct sampling stops at 14.4 MHz, so the shortwave bands above that need an upconverter. Shortwave also needs a long wire antenna, ideally outside.

### Running

The script needs Python 3.10 or later and some packages:

```
pip install numpy scipy pyaudio pyrtlsdr pyrtlsdrlib
```

Give a frequency in MHz, or give no frequency to start at 87.5 MHz.

When tuning to AM frequencies, specify them in MHz. For example, to listen to 1400 kHz, type "1.4".

Usage:

```
python sdr.py
python sdr.py 97.9
python sdr.py 1.4
python sdr.py 9.58
python sdr.py 127.575
python sdr.py 162.55
```

If you have more than one dongle, the script asks you to choose one before it starts playback.

The script picks US or European band settings from the country in your system settings. this is obtained through the Windows region, or the `LANG` setting on Linux and macOS. If that is not set, it falls back to US. You can override this by invoking `sdr.py` with `--region us` or `--region eu`:

```
python sdr.py 97.9 --region eu
```

On weather radio, each alert prints on its own line, for example `ALERT: Tornado Warning until 3:45 PM for 004013`, and stays on the status line until it expires. The numbers are county FIPS codes. To only get alerts for your county, add `--county` with its FIPS code. To keep the sound off until an alert arrives, like a weather radio, add `--alert-mode`:

```
python sdr.py 162.55 --county 004013 --alert-mode
```

Stations send a required weekly test, usually on Wednesday between 11 AM and noon local time. It shows as `ALERT: Required Weekly Test`.

### Keystrokes

The keys work on Windows only.

| Key | Action |
| --- | --- |
| Space | Play or pause |
| `_` | Volume down |
| `+` | Volume up |
| `s` | Go back one step (10 kHz on AM, 5 kHz on shortwave, 0.1 MHz on FM, 25 kHz on aviation and weather radio) |
| `w` | Go forward one step |
| `S` (Shift+S) | Scan back to the previous station |
| `W` (Shift+W) | Scan forward to the next station |
| `t` | Type a frequency in MHz |
| `m` | Mute or unmute |
| `i` | Show or hide the signal strength |
| `c` | Start or stop casting to Sonos |
| `h` | List the keys |
| Ctrl+C | Quit |

The keyboard's Previous Track and Next Track keys also scan, even when another window has focus.

### Casting to Sonos

Casting needs two more packages:

```
pip install soco lameenc
```

Add `--sonos` and the name of a speaker. The radio plays on that speaker's group, as the groups are set up in the Sonos app. Without a name, the script lists the groups for you to choose from. You can also press `c` to start or stop casting while the script runs.

```
python sdr.py 97.9 --sonos Kitchen
python sdr.py 97.9 --sonos
```

While casting:

* The computer is silent. The Sonos speakers play about 5 seconds behind the radio.
* Space, `_`, `+`, and `m` pause, change the volume of, and mute the Sonos group.
* The skip buttons on the speakers and in the Sonos app scan to the previous or next station.
* The Sonos app shows the frequency and station name, and the song from RDS.
* If someone plays something else on the speakers, the script plays on the computer again.

Casting replaces the Sonos queue for the group. When you stop casting or quit, the speakers stop.

The first time you cast, Windows may ask whether Python can use the network. Allow it on private networks, or the speakers cannot reach the script.

### Using the receiver from another program

`sdr.py` can also be imported. The receiver does not need the keyboard controls:

```python
import sdr

devices = sdr.list_devices()
receiver = sdr.Receiver(devices[0].index, 97.9, region="eu")
receiver.on_status_change = lambda: print(receiver.rds_name, receiver.rds_text)
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
| `Receiver(device_index, freq_mhz, region=None)` | Opens a dongle. `region` is `"us"` or `"eu"`. Without it, the receiver uses `detect_region()`, which reads the system's country setting. |
| `start()`, `stop()` | Start and stop the dongle and audio. |
| `tune(freq_mhz)`, `freq_mhz` | Change and read the frequency. AM, shortwave, FM, aviation, and NOAA frequencies all work. Other frequencies raise `ValueError`. |
| `band` | The current band, `sdr.AM`, `sdr.SW`, `sdr.FM`, `sdr.AIR`, or `sdr.NOAA`. |
| `seek(direction)` | Scans up (`1`) or down (`-1`) to the next station in the band and tunes to it. It wraps at the band edges, blocks while scanning (usually under 1 second), and returns the new frequency, or `None` if it found no other station. |
| `volume` | Volume from 0 to 100. |
| `paused`, `muted` | Pause or mute the audio. |
| `stereo` | True when the station sends stereo. |
| `signal_db` | Signal strength: how far the station is above the noise, in whole dB. |
| `rds_name`, `rds_text` | The station name and radio text sent with RDS, or empty text. FM stereo stations only. |
| `on_status_change` | Called with no arguments when `stereo`, `signal_db`, `rds_name`, or `rds_text` changes. It runs on a background thread. |
| `county` | A county FIPS code. When set, alerts for other counties are ignored. |
| `alert`, `on_alert` | The latest weather alert, an `sdr.Alert` with `name`, `event`, `locations`, `issued`, `expires`, and `describe()`. `on_alert` is called with each new alert from a background thread. |
| `running`, `error` | `running` becomes false if the dongle fails, and `error` holds the cause. |

## Other scripts

These scripts are in the `scripts` folder. They need Python 3.10 or later and use only the standard library. If you run one with no arguments, it asks you for input.

Some of these services (radio-locator.com, for example) limit how many requests one IP address can make. Not all of the limits are documented.

| Script | Source | Purpose |
| --- | --- | --- |
| `radiolocator.py` | radio-locator.com | Lists AM and FM stations near a zip code with distance, signal strength, and format. Shows full details for one call sign. |
| `zipsignal.py` | V-Soft ZipSignal | Lists AM and FM stations whose signal covers a zip code. |
| `tunein.py` | TuneIn | Searches stations by name, call sign, or location and prints their stream URLs. |
| `iheart.py` | iHeartRadio | Searches iHeartRadio stations and prints their stream URLs. |
| `streema.py` | Streema | Prints the direct stream URL for a call sign. |
| `broadcastify.py` | Broadcastify | Searches scanner feeds (fire, police, weather, and more) and prints their stream URLs. |

### Finding stations at a location

You can use `radiolocator.py`, `zipsignal.py`, or `tunein.py`.

`radiolocator.py` and `zipsignal.py` take a 5 digit US zip code:

```
python scripts/radiolocator.py 60601
python scripts/zipsignal.py 60601
```

To get full details for one station from the list, such as its owner, address, and transmitter data:

```
python scripts/radiolocator.py --info WBBM
python scripts/radiolocator.py --info WGN-AM
```

`tunein.py` takes a place name or a zip code and also prints the stream URLs:

```
python scripts/tunein.py --location "Chicago, IL"
python scripts/tunein.py --location 60601
```

### Finding the direct stream URL from a call sign

You can use `streema.py`, `tunein.py`, or `iheart.py`.

```
python scripts/streema.py WFMT
python scripts/streema.py WGN-AM
python scripts/tunein.py --callsign WFMT
```

`tunein.py` and `iheart.py` can also search by station name:

```
python scripts/tunein.py "jazz"
python scripts/iheart.py WGCI
```

### Finding fire, police, weather, etc

You can use `broadcastify.py`.

Search feeds by place or keyword. The results show the feed ID, status, and listener count:

```
python scripts/broadcastify.py "Cook County"
python scripts/broadcastify.py "NOAA weather"
```

Then get the stream URL with the feed ID or the feed name:

```
python scripts/broadcastify.py --stream 20973
```
