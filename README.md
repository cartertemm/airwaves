# Airwaves

If you don't have Python or don't want to worry about the internals, [download the Windows, macOS, or Linux app](https://github.com/cartertemm/airwaves/releases/latest).

This repository contains commands for digitally receiving and getting information about radio stations.

The primary application is `airwaves`, a radio receiver that plays AM, shortwave, FM, aviation, and NOAA weather radio from an RTL-SDR USB dongle. You can control it from the console or from an intuitive [web interface](#using-a-browser).

## Setting up Your RTLSDR

Before `airwaves` can use the dongle, the computer needs the right USB driver for it. You only do this once per computer. For more help, see the [RTL-SDR quick start guide](https://www.rtl-sdr.com/rtl-sdr-quick-start-guide/).

### Windows

Windows does not include a driver that works with the dongle. You will have to install the WinUSB driver with Zadig:

1. Plug in the dongle.
1. Download Zadig from [zadig.akeo.ie](https://zadig.akeo.ie/) and open it.
1. Press Alt to go to the menu, right arrow over to **Options**, and down arrow to **List All Devices**. If you do not see the dongle in the next step, also clear **Options > Ignore Hubs or Composite Parents**.
1. In the device list, select **Bulk-In, Interface (Interface 0)**. Some dongles show as **RTL2832U**, **RTL2832UHIDIR**, or **Blog V4** instead. Make sure the USB ID next to the list shows `0BDA 2838 00`. If you are using a screen reader, you may need to use object navigation (NVDA) or the JAWS cursor (JAWS) to reach the device list.

	**Warning:** Do not select any other device. Zadig replaces the driver of the device you select, meaning a wrong choice can stop your keyboard, mouse, or another device from working.

1. Make sure the box to the right of the selected device shows **WinUSB**.
1. Click **Replace Driver**. If Windows warns about the publisher, click **Install this driver software anyway**.

When Zadig finishes, the dongle is ready to use with `airwaves`.

### macOS

The macOS download is for Apple silicon and includes everything it needs. Unpack `airwaves-macos-arm64.tar.gz` and run `./airwaves 97.9` in Terminal. The app is not signed, so the first time, tell macOS to trust it:

```
xattr -d com.apple.quarantine airwaves
```

### Linux

The Linux download is for x86_64 PCs and includes the dongle driver and HD Radio. It needs glibc 2.35 or later, which Ubuntu 22.04, Debian 12, and newer distributions have. Unpack `airwaves-linux-x86_64.tar.gz` and run `./airwaves 97.9`.

Linux only lets root use the dongle until a udev rule gives other users access. The `rtl-sdr` package installs the rule:

```
sudo apt install rtl-sdr
```

On other distributions, the package is usually called `rtl-sdr` too. After installing it, unplug the dongle and plug it back in.

Linux may also load a TV driver, `dvb_usb_rtl28xxu`, for the dongle. The Linux download takes the dongle from it by itself. If `airwaves` says that this module is using the dongle, unload it and keep it from loading again:

```
sudo modprobe -r dvb_usb_rtl28xxu
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtl28xxu.conf
```

## Installing

The commands need Python 3.10 or later and [uv](https://docs.astral.sh/uv/). On macOS and Linux, first install the libraries in [docs/building.md](docs/building.md). Then, in this folder, run:

```
uv sync
```

Then run each command with `uv run`, for example `uv run airwaves 97.9`. Some features need extra packages. The `sonos` and `airplay` extras are for casting to Sonos speakers and AirPlay devices. The `web` extra is for controlling the radio from a browser. To install all of them, run:

```
uv sync --extra sonos --extra airplay --extra web
```

`uv sync` removes extras that you do not name. List every one you want.

To use the commands from any folder without `uv run`, install them as tools instead:

```
uv tool install ".[sonos,airplay,web]"
```

## Using the radio

### Features

* AM radio from 0.53 to 1.7 MHz.
* Shortwave radio from 2.3 to 14.4 MHz, in 5 kHz channels.
* FM radio in stereo, with the station name and radio text (often the artist and song) from RDS.
* HD Radio channels (HD1, HD2, and so on) on FM stations that send them, with the station name, channel names, and the song.
* The aviation band from 118.000 to 136.975 MHz, in 25 kHz channels. You will hear static between transmissions because aircraft and control towers only transmit when someone talks.
* NOAA weather radio from 162.400 to 162.550 MHz, with weather alerts. The script reads the alert codes (SAME) that stations send before each alert, and the 1050 Hz alarm tone.
* ACARS messages from aircraft, decoded on several channels at once.
* Scanning up or down to the next station in the band.
* US and European band settings. In Europe, AM is 531 to 1602 kHz in 9 kHz steps, FM uses 50 microsecond de-emphasis, and there is no NOAA weather radio.
* The status line and the window title show the frequency and optionally the signal strength.
* Casting to Sonos speakers, with the station and song shown in the Sonos app, or to AirPlay devices.
* Recording to MP3 or WAV files with one key.

AM and shortwave use the dongle's direct sampling mode. Some dongles need a hardware change before direct sampling picks up anything. Direct sampling stops at 14.4 MHz. Shortwave above 14.4 MHz needs an upconverter.

Shortwave also needs a long wire antenna, ideally placed outside.

HD Radio uses libnrsc5 from the [nrsc5](https://github.com/theori-io/nrsc5) project, which is included.

### Running

Give a frequency in MHz, or give no frequency to start at 87.5 MHz.

When tuning to AM frequencies, specify them in MHz. For example, to listen to 1400 kHz, type "1.4".

Usage:

```
uv run airwaves
uv run airwaves 97.9
uv run airwaves 1.4
uv run airwaves 9.58
uv run airwaves 127.575
uv run airwaves 162.55
```

Press `P` (Shift+P) to save the playing station, or HD channel, to the next free preset number. Press `p` to list the presets and type the number of the one to play, or nothing to cancel. A preset that is outside the bands of the current region shows as not available.

The volume and presets are saved to `airwaves.conf` in the current folder, and used the next time the script starts. The volume is saved each time you change it with `_` or `+`. Speaker volume while casting is not saved. The file looks like this, and you can edit it:

```
[airwaves]
volume = 80
gain = 30
ppm = 42

[presets]
1 = 97.9
2 = 99.9 HD2
3 = 1.4
```

`gain` and `ppm` are optional. They work like `--gain` and `--ppm` below, for every run.

If the file has an error, such as the same preset number twice, the radio might read only the settings above the error, and it does not save to the file. It will show a message with the line number instead. Fix or delete that line, and saving works again.

### Options

| Option | Purpose |
| --- | --- |
| `--region us`, `--region eu` | Use US or European band settings. The default comes from the Windows region, or the `LANG` setting on Linux and macOS. Without either, it is US. |
| `--gain DB` | Set the tuner gain, from 0 to 50 dB, or `auto`. Try it when strong stations nearby cause noise, or weak stations do not come in. The dongle uses the closest gain it has. The default is `gain` in `airwaves.conf`, or `auto`. |
| `--ppm PPM` | Correct the dongle's frequency error, from -200 to 200 parts per million. The default is `ppm` in `airwaves.conf`, or 0. |
| `--device N` | Use the Nth dongle, counting from 1. Without it, `airwaves` asks when you have more than one. |
| `--county FIPS` | Only show weather alerts for this county FIPS code. Alerts for the whole US always show. |
| `--alert-mode` | Keep the sound off until a weather alert arrives, like a weather radio. |
| `--record-format wav` | Record to WAV files. The default is MP3. |
| `--record-dir FOLDER` | Save recordings and `flights.log` in this folder. The default is the current folder. |
| `--acars` | Start by decoding ACARS. See ACARS. |
| `--log FILE` | Add each ACARS message to this file. See ACARS. |
| `--sonos [SPEAKER]`, `--airplay [DEVICE]` | Start casting. See Casting to Sonos or AirPlay. |
| `--web [PORT]` | Control the radio from a browser. See Using a browser. |
| `--web-password PASSWORD` | Ask browsers for this password. |
| `-v`, `--version` | Print the version and exit. |

For example:

```
uv run airwaves 162.55 --county 004013 --alert-mode --ppm 42
```

Most dongles tune a little above or below the frequency you ask for. On cheap dongles the error can be 50 ppm or more, which puts NOAA weather radio about 8 kHz off. Dongles with a TCXO (temperature compensated crystal), such as the RTL-SDR Blog V3 and V4, are usually within 2 ppm and do not need `--ppm`. A tool such as `rtl_test -p` or kalibrate-rtl can measure the error.

### Weather alerts

On weather radio, each alert prints on its own line, for example `ALERT: Tornado Warning until 3:45 PM for 004013`, and stays on the status line until it expires. The numbers are county FIPS codes.

Stations send a required weekly test, usually on Wednesday between 11 AM and noon local time. It shows as `ALERT: Required Weekly Test`.

### Recording

Press `r` to record what is playing to a file, and `r` again to stop. The file is named by the date, time, and frequency, for example `2026-10-07 14-30-05 97.9MHz.mp3`. Tuning, scanning, HD Radio, and casting do not stop the recording. Pausing leaves a gap, except while casting, when the space key pauses the speaker and the recording continues.

### ACARS

ACARS is a system that aircraft and ground stations use to send short text messages, such as position reports, weather requests, and gate information. Press `a` to decode ACARS, or start with `--acars`:

```
uv run airwaves --acars
```

Each message with text prints as one readable line containing the time, the flight and aircraft registration, where it flies from and to, what kind of message it is, and what it reports. For example, this message:

```
22:26 131.550 Y41747 XA-VLH: POSRPT 1747/06 KLAS/MMGL .XA-VLH /POS N33080W111591/ALT +36977/MCH 767/FOB 0080/ETA 0745
```

prints as:

```
22:26: Flight Y4 1747 (XA-VLH) from LAS (Las Vegas) to GDL (Guadalajara), position report, at 36,977 ft near CGZ (Casa Grande), Mach 0.767, fuel 80, ETA 00:45
```

Times show in your local time, and a position shows the closest airport. ACARS text has no single format, so any text the script does not understand prints after a `|` at the end of the line. Messages without text, such as acknowledgments, do not print.

If you find a message that is not printed correctly, please open an issue so we can fix it.

To also save the messages to a file, add `--log` with a file name. Each message adds the readable line, then the message as sent on the next line:

```
uv run airwaves --acars --log flights.log
```

While decoding ACARS, `r` appends messages to `flights.log` in the record folder (see `--record-dir`) in the same format, until you press `r` again. If a recording is already running when you enter ACARS mode, `r` stops that recording first.

The status line shows the channels and how many messages have printed. Press `a` again to go back to the frequency you were on. Tuning, stepping, or scanning also leaves ACARS mode.

The script decodes these channels at the same time:

| Region | Channels (MHz) |
| --- | --- |
| US | 130.425, 130.450, 131.125, 131.550 |
| Europe | 131.525, 131.725, 131.825 |

Limits:

* ACARS takes over the dongle. No sound plays, and you cannot listen to other frequencies (for example a control tower) while it decodes.
* The dongle receives 1.44 MHz at a time, which unfortunately means that only channels within that range decode together. In the US, 129.125 and 130.025 MHz are valid but outside this range.
* Aircraft only send ACARS when they are in range. If you are not near an airport or a common flight path, do not expect too many messages.

### Keystrokes

The keys work on Windows, macOS, and Linux.

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
| `a` | Start or stop decoding ACARS |
| `d` | Check for HD Radio, then go to the next HD channel. After the last channel, go back to analog. FM only. |
| `D` (Shift+D) | Check for HD Radio, then go to the previous HD channel. From HD1, go back to analog. |
| `c` | Start or stop casting to Sonos or AirPlay |
| `r` | Start or stop recording to a file. In ACARS mode, start or stop logging messages to `flights.log`. |
| `h` | List the keys |
| Ctrl+C | Quit |

On Windows, the keyboard's Previous Track and Next Track keys also scan, even when another window has focus.

When you press `d`, the analog sound stops and the script checks the station for HD Radio for up to 3 seconds. If it finds HD, HD1 plays and the status line shows the channel and how many the station has, for example `93.3 MHz HD2 of 3 | Oldies 92.7`. Channel names and more channels can show up a few seconds later. Moving between HD channels is instant. Tuning, stepping, or scanning goes back to analog.

### Casting to Sonos or AirPlay

Casting needs extra packages (see Installing): the `sonos` extra for Sonos, and the `airplay` extra for AirPlay.

Press `c` while the script runs to start or stop casting. It will list the Sonos groups and the AirPlay devices it finds for you to choose from. Sonos speakers will show up in both lists because they also support AirPlay.

To cast from the start, add `--sonos` or `--airplay` and a name. Without a name, the script lists only that kind for you to choose from.

```
uv run airwaves 97.9 --sonos Kitchen
uv run airwaves 97.9 --airplay Office
uv run airwaves 97.9 --sonos
```

While casting, the computer is silent, and Space, `_`, `+`, and `m` pause, change the volume of, and mute the speakers.

#### Sonos

* The radio plays on that speaker's group, as the groups are set up in the Sonos app.
* The Sonos speakers play about 4 seconds behind the radio. This is a limitation caused by the way that the local Sonos API works and not anything we have control over.
* The skip buttons on the speakers and in the Sonos app scan to the previous or next station.
* The Sonos app shows the frequency and station name, and the song from RDS.
* If someone plays something else on the speakers, the script plays on the computer again.
* If the speakers are unplugged or drop off the network, the script plays on the computer again after about 30 seconds.

Casting replaces the Sonos queue for the group. When you stop casting or quit, the speakers stop.

#### AirPlay

* AirPlay plays to one device at a time.
* The skip buttons on the device do not scan. Use the keys or the keyboard's media keys instead.
* The device shows the station, and the song from RDS when casting starts. It does not update while the station plays.
* Sonos speakers preserve their volume. Other AirPlay devices start at 30%.
* A Sonos speaker that is in a group leaves the group while AirPlay plays. When casting stops, the script puts it back, if the `sonos` extra is installed.

The first time you cast, Windows or macOS may ask whether Python can use the network. Allow it (on Windows, for private networks), otherwise the speakers will not be able to reach the script.

### Using a browser

`airwaves --web` runs the radio with no terminal keyboard controls and serves a page that any browser on your network can use.

This interface is far more user friendly if you aren't fond of the command line. It works equally well on mobile devices, and it lets you run Airwaves on a home server or a Raspberry Pi and listen anywhere.

It needs the `web` extra (see Installing).

```
uv run airwaves 97.9 --web
```

`airwaves` prints the address to open, such as `http://192.168.1.20:8000`. Use `--web 8080` for another port. If the port is in use, `airwaves` prints an error and exits.

The page works like a radio's front panel. Every command is both a button in the UI and a key when a keyboard is connected.

Short beeps play for key presses, while seeking, and at the end of a band. Settings (press S) turn each sound and spoken item on or off. The page speaks through a screen reader by default. If one is not running and you still want audio announcements, you can turn on Text to speech under Speech in Settings.

| Key | Action |
| --- | --- |
| Space | Play or pause |
| Left, Right | Step down, step up |
| Shift+Left, Shift+Right (or Ctrl+Left, Ctrl+Right) | Seek to the previous or next station |
| Up, Down | Volume up, volume down |
| M | Mute or unmute |
| F | Type a frequency |
| 1 to 0 | Tune to that preset. 0 is preset 10. |
| Shift+1 to Shift+0 | Save the station to that preset |
| B, Shift+B | Next band, previous band |
| D, Shift+D | Next and previous HD program. The first press checks for HD. |
| P | Presets. Delete clears the highlighted preset. You can also use the Clear button next to each preset. |
| O | Choose where the sound plays |
| I | Say what is playing |
| S | Settings |
| H | Help |

Escape goes back to the front panel from any other screen.

On a phone, open the page and add it to the home screen (in Safari, tap Share, then Add to Home Screen) to use it like an app.

Press O, or the Play on button, to choose where the sound plays:

* **Server speakers**: the sound card of the computer running `airwaves`. If "server speakers" is not listed, no soundcard was detected. Play, Mute, and the Up and Down keys then change the sound on that computer. Note that the radio starts paused by default.
* **This browser**: press Play to listen. Play, Mute, and the Up and Down keys then only change this browser. Several browsers can listen at once. On iPhone, iOS does not let a page set the volume. As such the volume slider is hidden unless you are listening on the server speakers or casting to another device on the network.
* **A Sonos or AirPlay speaker**: press Find Sonos and AirPlay speakers first. Needs the `sonos` or `airplay` extra. The panel shows a volume slider for the speaker.

Anyone on your network can open the page. To ask for a password, add `--web-password PASSWORD`. Note that browsers currently send it without encryption. Any username should work.

With more than one dongle, choose one with `--device N`, counting from 1. `--sonos` and `--airplay` need a speaker name with `--web`. Messages that the page shows also print in the console.

### Using the receiver from another program

To use the receiver from your own Python code, see [docs/api.md](docs/api.md).

## Other commands

The other commands (`radio-locator`, `zipsignal`, `tunein`, `iheart`, `streema`, and `broadcastify`) are unsupported for now. See [docs/other-commands.md](docs/other-commands.md).

## License

GPL version 3 or later, because `airwaves` includes libnrsc5. The Windows, macOS, and Linux apps also include the [osmocom rtl-sdr](https://gitea.osmocom.org/sdr/rtl-sdr) dongle driver (GPL version 2 or later). See `LICENSE`.
