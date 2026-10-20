"""Radio controls that the terminal and web frontends share. Nothing here reads or writes the console."""

import contextlib
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from functools import partial

import numpy as np

from . import config, flight_log, nrsc5
from .recorder import Recorder
from .sdr import ACARS_LOG_NAME, AUDIO_RATE, HD_LOCK_SECONDS, RECORD_TIME_FORMAT, HdUnavailable, band_for
from .sonos_cast import StreamServer

LOCAL = "local"
BROWSERS = "browsers"
HD_POLL_SECONDS = 0.02
LOCAL_TEXT = "Playing on the server."
BROWSERS_TEXT = "Playing in browsers. Press Play to listen."
NO_SPEAKERS = "No speakers found. Sonos needs the sonos extra and AirPlay the airplay extra."
PRESET_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(?:\s+HD(\d+))?", re.IGNORECASE)


@dataclass(frozen=True)
class Preset:
	"""A saved station: a frequency, and the HD channel (0 is HD1) or None for analog."""
	freq_mhz: float
	hd_program: int = None

	@classmethod
	def parse(cls, text):
		"""Returns the Preset written as text, like "97.9" or "99.9 HD2", or None if text is not one."""
		match = PRESET_PATTERN.fullmatch(text.strip())
		if match is None:
			return None
		program = int(match.group(2)) - 1 if match.group(2) else None
		if program is not None and program < 0:
			return None
		return cls(float(match.group(1)), program)

	def text(self):
		frequency = f"{self.freq_mhz:.4f}".rstrip("0").rstrip(".")
		return frequency if self.hd_program is None else f"{frequency} HD{self.hd_program + 1}"

	def describe(self, bands):
		"""Returns the preset for a menu, in the band's own format, or marked not available outside the bands."""
		band = band_for(self.freq_mhz, bands)
		if band is None:
			return f"{self.text()} (not available)"
		frequency = band.format(self.freq_mhz)
		return frequency if self.hd_program is None else f"{frequency} HD{self.hd_program + 1}"


@dataclass(frozen=True)
class CastTarget:
	"""A Sonos group or AirPlay device. make() returns a caster for it."""
	label: str
	names: list
	make: object


@dataclass(frozen=True)
class Status:
	"""What a frontend shows. frequency includes the HD channel or the ACARS range. output is LOCAL, BROWSERS, or "<name> (<kind>)" while casting."""
	frequency: str
	band: str
	freq_mhz: float
	station: str
	text: str
	signal_db: int
	mer: tuple | None
	hd_active: bool
	hd_program: int | None
	hd_programs: dict
	hd_lost: bool
	acars_active: bool
	acars_count: int
	alert: str | None
	output: str
	volume: int
	muted: bool
	paused: bool
	recording: bool
	scanning: bool


class Radio:
	"""Controls a Receiver for a frontend: tuning, HD Radio, presets, casting, recording, ACARS, and weather alerts.

	Assign on_status (called with no arguments) and on_message (called with one line of text; errors start with "error: "). Both run on any thread."""

	def __init__(self, receiver, alert_mode=False, log=None, record_format="mp3", record_dir="."):
		self.receiver = receiver
		receiver.on_status_change = self.notify_status
		receiver.on_alert = self.announce_alert
		receiver.on_acars = self.announce_acars
		self.on_status = None
		self.on_message = None
		self.acars_count = 0
		self.log = log
		self.record_format = record_format
		self.record_dir = record_dir
		self.recorder = None
		self.record_log = None
		self.alert_mode = alert_mode
		self.waiting_for_alert = alert_mode
		if alert_mode:
			receiver.muted = True
		self.caster = None
		self.browser_stream = None
		self.scanning = False
		# The web frontend sets this, so a cast that ends can go back to the browsers.
		self.browsers_available = False
		# Output changes come from the frontend and from caster threads (on_lost).
		self.lock = threading.RLock()

	@property
	def output(self):
		"""Where the sound goes, with volume, muted, and paused: the caster while casting, otherwise the receiver."""
		return self.caster or self.receiver

	@property
	def output_name(self):
		if self.caster:
			return f"{self.caster.name} ({self.caster.kind})"
		return BROWSERS if self.browser_stream else LOCAL

	def start_browsers(self):
		"""Sends the audio to the web frontend's stream instead of the sound card."""
		with self.lock:
			self.receiver.local_audio = False
			# A paused receiver gives the stream silence, and browsers pause on their own.
			self.receiver.paused = False
			self.browser_stream = StreamServer(self.receiver, AUDIO_RATE, None, serve_http=False, read_audio=self.browser_audio)
			self.browser_stream.start()

	def browser_audio(self, frame_count):
		"""Browsers set their own volume, so alert mode silences their stream here until an alert arrives."""
		audio = self.receiver.read_audio(frame_count)
		return np.zeros_like(audio) if self.waiting_for_alert else audio

	def stop_browsers(self):
		"""Stops the browser stream. The sound card stays off, so the next output can take over the audio."""
		with self.lock:
			stream, self.browser_stream = self.browser_stream, None
			stream.stop()

	def fall_back(self, to_browsers=False):
		"""Plays here, or in browsers if to_browsers or there is no sound card, after a cast ends or fails. Returns where the sound plays now."""
		with self.lock:
			if to_browsers or (self.browsers_available and not self.receiver.has_sound_card):
				self.start_browsers()
				return "Playing in the browser again."
			if self.receiver.has_sound_card:
				self.receiver.local_audio = True
				return "Playing here again."
			return "This computer has no sound card, so nothing plays."

	def set_output(self, target):
		"""Plays on target: LOCAL (the sound card), BROWSERS (the web frontend's stream), or a CastTarget."""
		with self.lock:
			if target == LOCAL and not self.receiver.has_sound_card:
				self.message("error: This computer has no sound card.")
				return
			if target == BROWSERS and self.browser_stream:
				self.message(BROWSERS_TEXT)
				return
			if target == LOCAL and not self.caster and not self.browser_stream:
				self.message(LOCAL_TEXT)
				return
			from_browsers = self.browser_stream is not None
			if self.caster:
				caster, self.caster = self.caster, None
				caster.stop()
			if self.browser_stream:
				self.stop_browsers()
			if target == BROWSERS:
				self.start_browsers()
				self.message(BROWSERS_TEXT)
			elif target == LOCAL:
				self.receiver.local_audio = True
				self.message(LOCAL_TEXT)
			else:
				self.start_cast(target, from_browsers)
		self.notify_status()

	def notify_status(self):
		if self.on_status:
			self.on_status()

	def message(self, text):
		if self.on_message:
			self.on_message(text)

	def status(self):
		receiver = self.receiver
		band = receiver.band
		hd_active = receiver.hd_active
		program = receiver.hd_program if hd_active else None
		frequency = band.format(receiver.freq_mhz)
		station = receiver.rds_name
		if hd_active:
			frequency += " HD" if program is None else f" HD{program + 1} of {len(receiver.hd_programs)}"
			station = receiver.hd_programs.get(program) or station
		if receiver.acars_active:
			frequency = f"ACARS {band.min_mhz:.3f} to {band.max_mhz:.3f} MHz"
		alert = receiver.alert
		output = self.output
		return Status(
			frequency=frequency,
			band=band.name,
			freq_mhz=receiver.freq_mhz,
			station=station,
			text=receiver.rds_text,
			signal_db=receiver.signal_db,
			mer=receiver.hd_mer if hd_active else None,
			hd_active=hd_active,
			hd_program=program,
			hd_programs=dict(receiver.hd_programs),
			hd_lost=program is not None and not receiver.hd_locked,
			acars_active=receiver.acars_active,
			acars_count=self.acars_count,
			alert=alert.name if alert and alert.active() else None,
			output=self.output_name,
			volume=output.volume,
			muted=output.muted,
			paused=output.paused,
			recording=bool(self.recorder or self.record_log),
			scanning=self.scanning,
		)

	def announce_alert(self, alert):
		if self.waiting_for_alert:
			self.waiting_for_alert = False
			self.receiver.muted = False
			if self.caster:
				self.caster.paused = False
		self.message(alert.describe())

	def announce_acars(self, message):
		if not message.text.strip():
			return
		self.acars_count += 1
		try:
			line = flight_log.describe(message)
		except Exception:
			# ACARS text has no fixed format, so show the message as sent rather than lose it.
			line = message.describe()
		self.message(line)
		entry = f"{line}\n\t{message.describe()}\n"
		if self.log:
			self.log.write(entry)
			self.log.flush()
		log = self.record_log
		if log:
			try:
				log.write(entry)
				log.flush()
			except ValueError:
				# The r key closed the log on the main thread while this message arrived.
				pass
			except OSError as error:
				self.record_log = None
				with contextlib.suppress(OSError):
					log.close()
				self.message(f"error: Recording stopped: {error}")

	def toggle_acars(self):
		receiver = self.receiver
		if receiver.acars_active:
			receiver.acars_stop()
			return
		self.announce_leaving_hd()
		self.acars_count = 0
		receiver.acars_start()
		channels = ", ".join(f"{freq_mhz:.3f}" for freq_mhz in receiver.band.acars_channels)
		self.message(f"Decoding ACARS on {channels} MHz. No sound plays.")

	def toggle_record(self):
		if self.recorder:
			recorder, self.recorder = self.recorder, None
			self.receiver.on_audio = None
			recorder.close()
			self.message(f"Saved {recorder.path}")
		elif self.record_log:
			log, self.record_log = self.record_log, None
			with contextlib.suppress(OSError):
				log.close()
			self.message(f"Saved {log.name}")
		elif self.receiver.acars_active:
			path = os.path.join(self.record_dir, ACARS_LOG_NAME)
			try:
				self.record_log = open(path, "a", encoding="utf-8")
			except OSError as error:
				self.message(f"error: Could not open the log file: {error}")
				return
			self.message(f"Logging ACARS to {path}")
		else:
			frequency = self.receiver.band.format(self.receiver.freq_mhz).replace(" ", "")
			name = f"{datetime.now().strftime(RECORD_TIME_FORMAT)} {frequency}.{self.record_format}"
			path = os.path.join(self.record_dir, name)
			try:
				recorder = Recorder(path, AUDIO_RATE, self.record_format == "mp3")
			except OSError as error:
				self.message(f"error: Could not open the recording: {error}")
				return
			recorder.on_error = self.lose_recording
			self.recorder = recorder
			self.receiver.on_audio = recorder.write
			self.message(f"Recording {path}")

	def lose_recording(self, error):
		"""Runs on the recorder thread when a write fails."""
		self.receiver.on_audio = None
		self.recorder = None
		self.message(f"error: Recording stopped: {error}")

	def announce_leaving_hd(self):
		if self.receiver.hd_active:
			self.message("Switching back to analog...")

	def start_hd(self):
		self.message("Checking for HD...")
		try:
			self.receiver.hd_start()
		except HdUnavailable as error:
			self.message(f"HD not available: {error}")
			return
		except nrsc5.NRSC5Error as error:
			self.message(f"error: Could not start HD: {error}")
			return
		threading.Thread(target=self.wait_for_hd_lock, args=(self.receiver.hd,), daemon=True).start()

	def wait_for_hd_lock(self, radio):
		"""Says when HD locks, or goes back to analog if it does not lock within HD_LOCK_SECONDS. Stops early if this HD session ends."""
		receiver = self.receiver
		deadline = time.monotonic() + HD_LOCK_SECONDS
		while time.monotonic() < deadline:
			if receiver.hd is not radio:
				return
			if receiver.hd_locked:
				self.message("HD found, retrieving channels...")
				return
			time.sleep(HD_POLL_SECONDS)
		if receiver.hd is radio:
			receiver.hd_stop()
			self.message(f"No HD on {receiver.band.format(receiver.freq_mhz)}.")

	def save_preset(self, number=None):
		"""Saves the current station to preset number, replacing what is there, or to the next free number."""
		receiver = self.receiver
		if receiver.acars_active:
			self.message("Cannot save a preset while decoding ACARS.")
			return
		current = Preset(receiver.freq_mhz, receiver.hd_program if receiver.hd_active else None)
		if number is None:
			for saved, text in config.presets().items():
				preset = Preset.parse(text)
				if preset and preset.text() == current.text():
					self.message(f"{current.describe(receiver.bands)} is already preset {saved}.")
					return
			number = config.next_preset_number()
		try:
			config.save(str(number), current.text(), config.PRESETS)
		except OSError as error:
			self.message(f"Could not save the preset to {config.FILE_NAME}: {error}")
			return
		self.message(f"{current.describe(receiver.bands)} saved to preset {number}")

	def delete_preset(self, number):
		if number not in config.presets():
			self.message(f"Preset {number} is empty.")
			return
		try:
			config.remove(str(number), config.PRESETS)
		except OSError as error:
			self.message(f"Could not change {config.FILE_NAME}: {error}")
			return
		self.message(f"Cleared preset {number}.")

	def tune_preset(self, preset):
		receiver = self.receiver
		if receiver.acars_active:
			receiver.acars_stop()
		self.announce_leaving_hd()
		receiver.tune(preset.freq_mhz)
		if preset.hd_program is None:
			self.notify_status()
			return
		self.start_hd()
		if receiver.hd_active:
			receiver.select_hd_program(preset.hd_program)

	def tune(self, freq_mhz):
		if band_for(freq_mhz, self.receiver.bands) is None:
			self.message("error: Frequency not in range.")
			return
		self.announce_leaving_hd()
		self.receiver.tune(freq_mhz)
		self.notify_status()

	def tune_band(self, name):
		"""Tunes to the lowest frequency of the band called name."""
		band = next((band for band in self.receiver.bands if band.name == name), None)
		if band is None:
			self.message(f"error: No band called {name}.")
			return
		self.tune(band.min_mhz)

	def step(self, direction):
		band = band_for(self.receiver.freq_mhz, self.receiver.bands)
		freq_mhz = self.receiver.freq_mhz + direction * band.step_mhz
		if band_for(freq_mhz, self.receiver.bands) is band:
			self.announce_leaving_hd()
			self.receiver.tune(freq_mhz)
			self.notify_status()

	def seek(self, direction):
		self.announce_leaving_hd()
		self.scanning = True
		self.notify_status()
		try:
			found = self.receiver.seek(direction)
		finally:
			self.scanning = False
		if found is None and self.receiver.running:
			self.message("No other station found.")
		else:
			self.notify_status()

	def step_hd(self, direction):
		"""Moves through analog, HD1, HD2, and so on: forward for direction 1, back for -1."""
		receiver = self.receiver
		if not receiver.band.hd:
			self.message("HD works only on FM.")
			return
		if not receiver.hd_active:
			self.start_hd()
			return
		program = receiver.hd_program_step(direction)
		if program is None:
			self.message("Switching back to analog...")
			receiver.hd_stop()
			return
		self.play_hd_program(program)

	def select_hd(self, program):
		"""Plays HD channel program of the current station (0 is HD1), starting HD first if needed. None goes back to analog."""
		receiver = self.receiver
		if program is None:
			if receiver.hd_active:
				self.message("Switching back to analog...")
				receiver.hd_stop()
			return
		if not receiver.band.hd:
			self.message("HD works only on FM.")
			return
		if not receiver.hd_active:
			self.start_hd()
			if not receiver.hd_active:
				return
		self.play_hd_program(program)

	def play_hd_program(self, program):
		self.receiver.select_hd_program(program)
		self.message(f"HD{program + 1} {self.receiver.hd_programs.get(program, '')}".strip())

	def presets(self):
		"""Returns (number, label, available) for each saved preset, in number order."""
		bands = self.receiver.bands
		found = []
		for number, text in config.presets().items():
			preset = Preset.parse(text)
			label = preset.describe(bands) if preset else f"{text} (not available)"
			found.append((number, label, preset is not None and band_for(preset.freq_mhz, bands) is not None))
		return found

	def choose_preset(self, number):
		text = config.presets().get(number)
		preset = Preset.parse(text) if text else None
		if preset is None or band_for(preset.freq_mhz, self.receiver.bands) is None:
			self.message(f"error: Preset {number} is not available.")
			return
		self.tune_preset(preset)

	def set_volume(self, percent):
		"""Sets the output's volume. The receiver's volume is saved for next time."""
		output = self.output
		output.volume = percent
		if output is self.receiver:
			try:
				config.save("volume", output.volume)
			except OSError as error:
				self.message(f"Could not save the volume to {config.FILE_NAME}: {error}")
		self.notify_status()

	def change_volume(self, delta):
		self.set_volume(self.output.volume + delta)

	def set_muted(self, muted):
		self.output.muted = muted
		self.notify_status()

	def set_paused(self, paused):
		self.output.paused = paused
		self.notify_status()

	def cast_targets(self, kinds, name=None):
		"""Returns a CastTarget for each Sonos group and AirPlay device found, sorted so the same room sits together.

		With name, only targets with a speaker of that name. Each kind needs its extra packages; a kind whose packages are missing finds nothing. Sends an error message when nothing is found."""
		targets = []
		if "sonos" in kinds:
			try:
				from . import sonos_cast
				groups = sonos_cast.find_groups()
			except ImportError:
				groups = []
			targets += [CastTarget(f"{sonos_cast.group_label(group)} (Sonos)", [member.player_name for member in group.members], partial(sonos_cast.Caster, self.receiver, group, AUDIO_RATE)) for group in groups]
		if "airplay" in kinds:
			try:
				from . import airplay_cast
				devices = airplay_cast.find_devices()
			except ImportError:
				devices = []
			targets += [CastTarget(f"{device.name} (AirPlay)", [device.name], partial(airplay_cast.AirPlayCaster, self.receiver, device, AUDIO_RATE)) for device in devices]
		if name:
			targets = [target for target in targets if name.lower() in (target_name.lower() for target_name in target.names)]
		if not targets:
			self.message(f"error: No speaker named {name}." if name else f"error: {NO_SPEAKERS}")
		return sorted(targets, key=lambda target: target.label.lower())

	def start_cast(self, target, from_browsers=False):
		"""Plays on target instead of here. Returns False, after an error message, if it cannot. from_browsers says the browsers played before, so they play again if the cast fails."""
		with self.lock:
			try:
				caster = target.make()
				caster.on_skip = self.seek
				caster.on_change = self.notify_status
				caster.on_lost = partial(self.cast_lost, caster)
				caster.start()
			except Exception as error:
				self.message(f"error: Could not cast to {target.label}: {str(error).rstrip('.')}. {self.fall_back(from_browsers)}")
				return False
			self.caster = caster
			if self.waiting_for_alert:
				caster.paused = True
			self.message(f"Casting to {target.label}")
			return True

	def stop_cast(self):
		with self.lock:
			caster, self.caster = self.caster, None
			if caster is None:
				return
			caster.stop()
			self.message(f"Stopped casting. {self.fall_back()}")
		self.notify_status()

	def cast_lost(self, caster):
		"""Runs on a caster thread when caster stops playing the radio. Does nothing if the output has changed since."""
		with self.lock:
			if caster is not self.caster:
				return
			self.caster = None
			caster.stop(release=False)
			self.message(f"{caster.kind}: {caster.name} stopped playing the radio. {self.fall_back()}")
		self.notify_status()

	def close(self):
		"""Stops recording, casting, and the browser stream. Call it before Receiver.stop()."""
		if self.recorder or self.record_log:
			self.toggle_record()
		with self.lock:
			caster, self.caster = self.caster, None
			if caster:
				caster.stop()
			if self.browser_stream:
				self.stop_browsers()
