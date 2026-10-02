# Radio Utils

A set of CLI based utilities having to do with discovering nearby radio stations, finding their stream URLs, and ultimately playing them.

These were mostly written a few years ago (before the GenAI era). I have continued maintaining them because I have found them useful. I hope someone else does so too!

Please note that some of these services (radio locator for instance) impose IP-based rate limits. Not all of them are documented. It is important to do your own A/B testing and be mindful of this so you don't encounter them in an application.

All scripts need Python 3.10 or later. All scripts except `sdr.py` use only the standard library.

Here is a list of the available scripts:

| Script | Source | Purpose |
| --- | --- | --- |
| `radiolocator.py` | radio-locator.com | Lists AM and FM stations near a zip code with distance, signal strength, and format. Shows full details for one call sign. |
| `zipsignal.py` | V-Soft ZipSignal | Lists AM and FM stations whose signal covers a zip code. |
| `tunein.py` | TuneIn | Searches stations by name, call sign, or location and prints their stream URLs. |
| `iheart.py` | iHeartRadio | Searches iHeartRadio stations and prints their stream URLs. |
| `streema.py` | Streema | Prints the direct stream URL for a call sign. |
| `broadcastify.py` | Broadcastify | Searches scanner feeds (fire, police, weather, and more) and prints their stream URLs. |
| `sdr.py` | RTL-SDR dongle | Plays AM radio, shortwave radio, FM stereo radio, aviation radio, and NOAA weather radio from an RTL-SDR USB dongle. |

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

## Listening to AM, shortwave, FM, aviation, or weather radio with an RTL-SDR dongle

You can use `sdr.py`. It needs some packages:

```
pip install numpy scipy pyaudio pyrtlsdr pyrtlsdrlib
```

Give a frequency in MHz, or give no frequency to start at 87.5 MHz:

```
python sdr.py 97.9
python sdr.py
```

NOAA weather radio works the same way. Give a channel from 162.400 to 162.550 MHz:

```
python sdr.py 162.55
```

For AM radio, give the frequency in MHz, from 0.53 to 1.7. For example, 1400 kHz is 1.4:

```
python sdr.py 1.4
```

Shortwave radio is 2.3 to 14.4 MHz, in 5 kHz channels:

```
python sdr.py 9.58
```

AM and shortwave use the dongle's direct sampling mode. Some dongles need a hardware change before direct sampling picks up anything. Direct sampling stops at 14.4 MHz, so the shortwave bands above that need an upconverter. Shortwave also needs a long wire antenna, ideally outside.

The aviation band is 118.000 to 136.975 MHz, in 25 kHz channels:

```
python sdr.py 127.575
```

Aircraft and control towers only transmit when someone talks, so you hear static between transmissions.

If you have more than one dongle, the script asks you to choose one.

The script uses US or European band settings. It picks them from the country in your system settings: the Windows region, or the `LANG` setting on Linux and macOS. If that is not set, it uses US settings. To choose, add `--region us` or `--region eu`:

```
python sdr.py 97.9 --region eu
```

In Europe, AM is 531 to 1602 kHz in 9 kHz steps, FM uses 50 microsecond de-emphasis, and there is no NOAA weather radio.

The status line and the window title show the frequency. Press `i` to also show the signal strength. On FM stations that send RDS, they also show the station name and the radio text, which is often the artist and song.

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
| `h` | List the keys |
| Ctrl+C | Quit |

The keys work on Windows only.

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
| `running`, `error` | `running` becomes false if the dongle fails, and `error` holds the cause. |
