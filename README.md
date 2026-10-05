# Airwaves

This repository contains commands for digitally receiving and getting information about radio stations.

The primary application is `sdr`, a radio receiver that plays AM, shortwave, FM, aviation, and NOAA weather radio from an RTL-SDR USB dongle. The other commands find nearby stations and their stream URLs through online services such as TuneIn and Broadcastify.

## Installing

The commands need Python 3.10 or later and [uv](https://docs.astral.sh/uv/). In this folder, run:

```
uv sync
```

Then run each command with `uv run`, for example `uv run sdr 97.9` or `uv run tunein "jazz"`. To cast to Sonos speakers or AirPlay devices, install the extra packages for them:

```
uv sync --extra sonos --extra airplay
```

To use the commands from any folder without `uv run`, install them as tools instead:

```
uv tool install ".[sonos,airplay]"
```

### Building a Windows executable

To give the receiver to someone who does not have Python, run `build.bat`. It builds `dist\sdr.exe`, one file that includes Python, the packages, and the dongle driver, with Sonos and AirPlay casting:

```
build.bat
```

The other commands are not in the executable.

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
* Casting to Sonos speakers, with the station and song shown in the Sonos app, or to AirPlay devices.

AM and shortwave use the dongle's direct sampling mode. Some dongles need a hardware change before direct sampling picks up anything. Direct sampling stops at 14.4 MHz, so the shortwave bands above that need an upconverter. Shortwave also needs a long wire antenna, ideally outside.

### Running

Give a frequency in MHz, or give no frequency to start at 87.5 MHz.

When tuning to AM frequencies, specify them in MHz. For example, to listen to 1400 kHz, type "1.4".

Usage:

```
uv run sdr
uv run sdr 97.9
uv run sdr 1.4
uv run sdr 9.58
uv run sdr 127.575
uv run sdr 162.55
```

If you have more than one dongle, the script asks you to choose one before it starts playback.

The script picks US or European band settings from the country in your system settings. this is obtained through the Windows region, or the `LANG` setting on Linux and macOS. If that is not set, it falls back to US. You can override this by invoking `sdr` with `--region us` or `--region eu`:

```
uv run sdr 97.9 --region eu
```

On weather radio, each alert prints on its own line, for example `ALERT: Tornado Warning until 3:45 PM for 004013`, and stays on the status line until it expires. The numbers are county FIPS codes. To only get alerts for your county, add `--county` with its FIPS code. To keep the sound off until an alert arrives, like a weather radio, add `--alert-mode`:

```
uv run sdr 162.55 --county 004013 --alert-mode
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
| `c` | Start or stop casting to Sonos or AirPlay |
| `h` | List the keys |
| Ctrl+C | Quit |

The keyboard's Previous Track and Next Track keys also scan, even when another window has focus.

### Casting to Sonos or AirPlay

Casting needs extra packages (see Installing): the `sonos` extra for Sonos, and the `airplay` extra for AirPlay.

Press `c` while the script runs to start or stop casting. It lists the Sonos groups and the AirPlay devices it finds, side by side, for you to choose from. Sonos speakers also support AirPlay, so they show up in both lists.

To cast from the start, add `--sonos` or `--airplay` and a name. Without a name, the script lists only that kind for you to choose from.

```
uv run sdr 97.9 --sonos Kitchen
uv run sdr 97.9 --airplay Office
uv run sdr 97.9 --sonos
```

While casting, the computer is silent, and Space, `_`, `+`, and `m` pause, change the volume of, and mute the speakers.

#### Sonos

* The radio plays on that speaker's group, as the groups are set up in the Sonos app.
* The Sonos speakers play about 4 seconds behind the radio.
* The skip buttons on the speakers and in the Sonos app scan to the previous or next station.
* The Sonos app shows the frequency and station name, and the song from RDS.
* If someone plays something else on the speakers, the script plays on the computer again.

Casting replaces the Sonos queue for the group. When you stop casting or quit, the speakers stop.

#### AirPlay

* AirPlay plays to one device at a time.
* The skip buttons on the device do not scan. Use the keys or the keyboard's media keys instead.
* The device shows the station, and the song from RDS when casting starts. It does not update while the station plays.
* Sonos speakers keep their volume. Other AirPlay devices start at 30%.
* A Sonos speaker that is in a group leaves the group while AirPlay plays. When casting stops, the script puts it back, if the `sonos` extra is installed.

The first time you cast, Windows may ask whether Python can use the network. Allow it on private networks, or the speakers cannot reach the script.

### Using the receiver from another program

`sdr` can also be imported from another program. The receiver does not need the keyboard controls:

```python
from airwaves import sdr

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

## Other commands

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

### Finding stations at a location

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

### Finding the direct stream URL from a call sign

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

### Finding fire, police, weather, etc

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
