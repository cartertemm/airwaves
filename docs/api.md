# Using the receiver from another program

The receiver can also be used from another program. The receiver does not need the keyboard controls:

```python
import airwaves

devices = airwaves.list_devices()
receiver = airwaves.Receiver(devices[0].index, 97.9, region="eu")
receiver.on_status_change = lambda: print(receiver.rds_name, receiver.rds_text)
receiver.start()
receiver.volume = 70
receiver.tune(98.7)
receiver.muted = True
receiver.paused = True
receiver.hd_start()
receiver.select_hd_program(1)
receiver.stop()
```

| Member | Purpose |
| --- | --- |
| `list_devices()` | Returns the connected dongles, each with `index`, `name`, and `serial`. |
| `Receiver(device_index, freq_mhz, region=None, gain="auto", ppm=0)` | Opens a dongle. `region` is `"us"` or `"eu"`. Without it, the receiver uses `detect_region()`, which reads the system's country setting. `gain` is `"auto"` or the tuner gain in dB. `ppm` corrects the dongle's frequency error. |
| `start()`, `stop()` | Start and stop the dongle and audio. |
| `tune(freq_mhz)`, `freq_mhz` | Change and read the frequency. AM, shortwave, FM, aviation, and NOAA frequencies all work. Other frequencies raise `ValueError`. |
| `band` | The current band, `airwaves.AM`, `airwaves.SW`, `airwaves.FM`, `airwaves.AIR`, or `airwaves.NOAA`. While ACARS decodes, it is `airwaves.ACARS` or `airwaves.ACARS_EU`. |
| `seek(direction)` | Scans up (`1`) or down (`-1`) to the next station in the band and tunes to it. It wraps at the band edges, blocks while scanning (usually under 1 second), and returns the new frequency, or `None` if it found no other station. |
| `volume` | Volume from 0 to 100. |
| `paused`, `muted` | Pause or mute the audio. |
| `stereo` | True when the station sends stereo. |
| `signal_db` | Signal strength: how far the station is above the noise, in whole dB. |
| `rds_name`, `rds_text` | The station name and radio text sent with RDS, or empty text. FM stereo stations only. |
| `hd_start()`, `hd_stop()`, `hd_active` | Start and stop HD Radio on the current FM station. `hd_start()` raises `airwaves.HdUnavailable` if libnrsc5 cannot load. It raises `airwaves.nrsc5.NRSC5Error` if nrsc5 cannot open the dongle, and analog plays again. While HD is active, `tune()` and `seek()` go back to analog first. |
| `hd_locked`, `hd_mer` | Whether HD is locked, and the last digital signal quality as `(lower, upper)` dB. |
| `hd_programs`, `hd_program`, `select_hd_program(program)`, `hd_program_step(direction)` | The HD channels found, as a dict of program number to name (0 is HD1), the playing channel, how to play another, and the channel after (`1`) or before (`-1`) the playing one (`None` past either end). HD1 plays by itself once its audio arrives. HD can take about 3 seconds to lock, so a program that uses the API should wait for `hd_locked` and go back with `hd_stop()` if it does not lock. While HD is active, `rds_name` is the HD station name and `rds_text` is "artist - title". |
| `on_status_change` | Called with no arguments when `stereo`, `signal_db`, `rds_name`, `rds_text`, or the HD state changes. It runs on a background thread. |
| `on_audio` | Called with each block of stereo audio (a float32 numpy array of shape `(frames, 2)` at 48 kHz, before volume and mute) from a background thread. Not called while paused. The `r` key uses it to record. |
| `acars_start()`, `acars_stop()`, `acars_active` | Start and stop decoding ACARS. `acars_start()` tunes to the region's ACARS channels and plays silence. `acars_stop()` goes back to `freq_mhz`, which `acars_start()` does not change. `tune()` and `seek()` also stop ACARS. |
| `on_acars` | Called with each decoded ACARS message from a background thread, including messages without text. Each is an `airwaves.AcarsMessage` with `time`, `freq_mhz`, `mode`, `registration`, `label`, `block_id`, `flight`, `number`, `text`, and `describe()`. `flight` and `number` are only set on messages from aircraft. `flight_log.describe(message)` (`from airwaves import flight_log`) returns the readable line. |
| `county` | A county FIPS code. When set, alerts for other counties are ignored. Alerts for the whole US always show. |
| `alert`, `on_alert` | The latest weather alert, an `airwaves.Alert` with `name`, `event`, `locations`, `issued`, `expires`, and `describe()`. `on_alert` is called with each new alert from a background thread. |
| `running`, `error` | `running` becomes false if the dongle fails, and `error` holds the cause. |
| `has_sound_card` | False when no sound card could be opened. `local_audio` then stays False; cast or use the web frontend instead. |

Frontends can use `airwaves.radio.Radio(receiver)` for presets, casting, HD stepping, and alerts. Assign `on_status` and `on_message` to get callbacks, and call `status()` for the current state.
