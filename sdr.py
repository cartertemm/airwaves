import argparse
import collections
import ctypes
import queue
import shutil
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np
import pyaudio
from rtlsdr import RtlSdr
from rtlsdr.librtlsdr import librtlsdr
from scipy import signal

VOLUME_STEP = 10
DEFAULT_VOLUME = 50
MAX_VOLUME = 100
# Station audio peaks near full scale, so leave headroom for the sound card.
OUTPUT_LEVEL = 0.5

SDR_RATE = 1440000
# A loud stereo signal is about 256 kHz wide, so this rate leaves room for all of it.
MPX_RATE = 288000
AUDIO_RATE = 48000
SDR_DECIMATION = SDR_RATE // MPX_RATE
AUDIO_DECIMATION = MPX_RATE // AUDIO_RATE
# Tune below the station so the dongle's DC spike stays out of the channel.
# A quarter of the sample rate makes the mixer the repeating sequence 1, -j, -1, j.
TUNE_OFFSET = SDR_RATE // 4
BLOCK_SIZE = 153600
SDR_GAIN = "auto"

CHANNEL_CUTOFF = 120000
CHANNEL_TAPS = 151
PILOT_FREQ = 19000
PILOT_HALF_WIDTH = 500
PILOT_TAPS = 201
AUDIO_TAPS = 151
PILOT_NOISE_BAND = (16000, 18500)
STEREO_THRESHOLD = 10.0
# Stations send the pilot at about 0.1 of full deviation.
PILOT_MIN_LEVEL = 0.02
PILOT_SMOOTHING = 0.3
# Removes the AM carrier level, which is everything below about 20 Hz.
DC_BLOCK_POLE = 1 - 2 * np.pi * 20 / MPX_RATE
RDS_FREQ = 57000
RDS_HALF_WIDTH = 2400
# The RDS bit clock is the pilot divided by 16, so one bit lasts 16 pilot cycles.
RDS_BIT_PHASE = 16 * 2 * np.pi
RDS_TIMING_STEPS = 16
RDS_AXIS_SMOOTHING = 0.9
RDS_BLOCK_BITS = 26
RDS_POLYNOMIAL = 0x1B9
# Offset words for blocks A, B, C or C', and D.
RDS_OFFSETS = ((0x0FC,), (0x198,), (0x168, 0x350), (0x1B4,))
RDS_SYNC_LOSS_BLOCKS = 10
RDS_NAME_LENGTH = 8
RDS_TEXT_END = "\r"
# The dongle delivers audio in bursts, so hold some back to keep the sound card fed between bursts.
PREFILL_FRAMES = AUDIO_RATE // 4
MAX_BUFFER_FRAMES = AUDIO_RATE
MAX_QUEUED_BLOCKS = 10
QUEUE_TIMEOUT_SECONDS = 0.5
# After a retune, the first 1 to 2 ms of samples are noise from the tuner settling.
SETTLE_FRAMES = AUDIO_RATE * 5 // 1000
FADE_FRAMES = AUDIO_RATE * 20 // 1000
# Samples used to measure the signal level, both while scanning and while playing.
SCAN_SAMPLES = 32768
SIGNAL_SMOOTHING = 0.3
# The shown signal level only changes once the measured level moves this far from it, so it does not flicker between two numbers.
SIGNAL_HYSTERESIS_DB = 1
# Skip the tuner settling noise after each retune while scanning.
SCAN_SETTLE_BYTES = 8192
# HD Radio sidebands sit two channels from a station and 14 dB or more below it.
SCAN_SIDEBAND_RATIO = 10 ** (10 / 10)

KEY_POLL_SECONDS = 0.02
TITLE_LENGTH = 1024


@dataclass(frozen=True)
class Band:
	min_mhz: float
	max_mhz: float
	step_mhz: float
	digits: int
	max_deviation: int | None
	# A second, narrower channel filter after the first decimation. None skips it.
	narrow_cutoff: int | None
	audio_cutoff: int
	stereo: bool
	deemphasis_tau: float | None
	am: bool = False
	# How far above the noise a channel must be for a scan to stop there.
	scan_threshold_db: float = 5
	# Bands below the tuner's range feed the antenna straight to the dongle's converter.
	direct_sampling: bool = False


# North American de-emphasis. Europe uses 50 microseconds.
FM = Band(min_mhz=87.5, max_mhz=108.0, step_mhz=0.1, digits=1, max_deviation=75000, narrow_cutoff=None, audio_cutoff=15000, stereo=True, deemphasis_tau=75e-6)
NOAA = Band(min_mhz=162.4, max_mhz=162.55, step_mhz=0.025, digits=3, max_deviation=5000, narrow_cutoff=8000, audio_cutoff=4000, stereo=False, deemphasis_tau=None)
AM = Band(min_mhz=0.53, max_mhz=1.7, step_mhz=0.01, digits=2, max_deviation=None, narrow_cutoff=5000, audio_cutoff=5000, stereo=False, deemphasis_tau=None, am=True, direct_sampling=True, scan_threshold_db=13)
BANDS = (AM, FM, NOAA)


def band_for(freq_mhz):
	"""Returns the band that holds freq_mhz, or None."""
	return next((band for band in BANDS if band.min_mhz <= round(freq_mhz, 3) <= band.max_mhz), None)


def channel_powers(samples, band):
	"""Returns the noise floor, then the power in the channel at TUNE_OFFSET and in the channels one and two steps below and above it."""
	power = np.abs(np.fft.fft(samples * np.hanning(len(samples)))) ** 2
	freqs = np.fft.fftfreq(len(samples), 1 / SDR_RATE)
	half_width = band.narrow_cutoff or band.step_mhz * 1e6 / 2
	step = band.step_mhz * 1e6
	return np.median(power), *(power[np.abs(freqs - TUNE_OFFSET - offset) < half_width].mean() for offset in (0, -step, step, -2 * step, 2 * step))


def rds_checkword(data):
	"""Returns the 10 bit checkword for 16 data bits, before the offset word is added."""
	check = 0
	for i in range(15, -1, -1):
		feedback = ((data >> i) ^ (check >> 9)) & 1
		check = (check << 1) & 0x3FF
		if feedback:
			check ^= RDS_POLYNOMIAL
	return check


def rds_chars(word):
	return [chr(byte) if 0x20 <= byte < 0x7F or chr(byte) == RDS_TEXT_END else " " for byte in (word >> 8, word & 0xFF)]


class RdsDecoder:
	"""Decodes the station name and radio text from the RDS signal of one FM station."""

	def __init__(self):
		self.taps = signal.firwin(PILOT_TAPS, [RDS_FREQ - RDS_HALF_WIDTH, RDS_FREQ + RDS_HALF_WIDTH], pass_zero=False, fs=MPX_RATE)
		self.state = np.zeros(PILOT_TAPS - 1)
		self.reset()

	def reset(self):
		self.theta = None
		self.baseband = np.zeros(0, dtype=complex)
		self.bit_phase = np.zeros(0)
		self.timing = None
		self.axis = 0j
		self.last_symbol = False
		self.register = 0
		self.position = None
		self.bit_count = 0
		self.bad_blocks = 0
		self.group = [None] * 4
		self.name_chars = [" "] * RDS_NAME_LENGTH
		self.name_segments = 0
		self.name_frame = None
		self.text_chars = []
		self.text_segments = set()
		self.text_flag = None
		self.name = ""
		self.text = ""

	def process(self, mpx, pilot):
		"""Takes the multiplex signal and the analytic pilot, which the band-pass filter here delays by the same amount."""
		rds, self.state = signal.lfilter(self.taps, 1, mpx, zi=self.state)
		angles = np.angle(pilot)
		theta = np.unwrap(np.concatenate(([angles[0] if self.theta is None else self.theta], angles)))[1:]
		self.theta = theta[-1]
		# The 57 kHz carrier is the third harmonic of the pilot.
		carrier = (pilot / np.maximum(np.abs(pilot), 1e-12)) ** 3
		self.baseband = np.concatenate((self.baseband, rds * np.conj(carrier)))
		self.bit_phase = np.concatenate((self.bit_phase, theta / RDS_BIT_PHASE))
		if self.timing is None:
			self.timing = max(np.arange(RDS_TIMING_STEPS) / RDS_TIMING_STEPS, key=lambda timing: np.abs(self.integrate(timing)[0]).sum())
		bits, incomplete = self.integrate(self.timing)
		self.baseband, self.bit_phase = self.baseband[incomplete], self.bit_phase[incomplete]
		self.axis = RDS_AXIS_SMOOTHING * self.axis + (bits ** 2).sum()
		symbols = (bits * np.exp(-0.5j * np.angle(self.axis))).real > 0
		# Each bit is sent as the change from the previous symbol.
		for bit in symbols != np.concatenate(([self.last_symbol], symbols[:-1])):
			self.receive_bit(int(bit))
		self.last_symbol = symbols[-1]

	def integrate(self, timing):
		"""Returns each complete bit as its first half minus its second half, and which samples belong to the last, incomplete bit."""
		position = self.bit_phase - timing
		index = np.floor(position).astype(int)
		index -= index[0]
		weights = self.baseband * np.where(position - np.floor(position) < 0.5, 1, -1)
		bits = np.bincount(index, weights.real) + 1j * np.bincount(index, weights.imag)
		return bits[:-1], index == index[-1]

	def receive_bit(self, bit):
		self.register = ((self.register << 1) | bit) & ((1 << RDS_BLOCK_BITS) - 1)
		syndrome = (self.register & 0x3FF) ^ rds_checkword(self.register >> 10)
		if self.position is None:
			self.position = next((position for position, offsets in enumerate(RDS_OFFSETS) if syndrome in offsets), None)
			if self.position is not None:
				self.bit_count = 0
				self.bad_blocks = 0
				self.store(self.register >> 10)
			return
		self.bit_count += 1
		if self.bit_count < RDS_BLOCK_BITS:
			return
		self.bit_count = 0
		self.position = (self.position + 1) % 4
		if syndrome in RDS_OFFSETS[self.position]:
			self.bad_blocks = 0
			self.store(self.register >> 10)
			return
		self.group[self.position] = None
		self.bad_blocks += 1
		if self.bad_blocks >= RDS_SYNC_LOSS_BLOCKS:
			self.position = None

	def store(self, data):
		if self.position == 0:
			self.group = [data, None, None, None]
			return
		self.group[self.position] = data
		if self.position == 3 and None not in self.group:
			self.parse(*self.group)

	def parse(self, a, b, c, d):
		group_type, version_b = b >> 12, (b >> 11) & 1
		if group_type == 0:
			segment = b & 0x3
			# Stations send the name in order, and some scroll text through it, so start over at each first segment to avoid mixing two names.
			if segment == 0:
				self.name_segments = 0
			self.name_chars[segment * 2:segment * 2 + 2] = rds_chars(d)
			self.name_segments |= 1 << segment
			if self.name_segments == 0xF:
				# A station can change the text partway through sending it, so only show a name once it arrives the same way twice in a row.
				frame = "".join(self.name_chars)
				if frame == self.name_frame:
					self.name = frame.strip()
				self.name_frame = frame
				self.name_segments = 0
		elif group_type == 2:
			chars = rds_chars(d) if version_b else rds_chars(c) + rds_chars(d)
			flag = (b >> 4) & 1
			if flag != self.text_flag:
				self.text_flag = flag
				self.text_chars = [" "] * 16 * len(chars)
				self.text_segments = set()
			segment = b & 0xF
			self.text_chars[segment * len(chars):(segment + 1) * len(chars)] = chars
			self.text_segments.add(segment)
			text = "".join(self.text_chars)
			end = text.find(RDS_TEXT_END) if RDS_TEXT_END in text else len(text)
			if self.text_segments >= set(range((end + len(chars) - 1) // len(chars))):
				self.text = text[:end].strip()


class Demodulator:
	"""Turns blocks of raw IQ samples at SDR_RATE into audio at AUDIO_RATE for one band."""

	def __init__(self, band):
		self.band = band
		n = np.arange(BLOCK_SIZE)
		self.mixer = np.exp(-2j * np.pi * TUNE_OFFSET * n / SDR_RATE)
		self.channel_taps = signal.firwin(CHANNEL_TAPS, CHANNEL_CUTOFF, fs=SDR_RATE)
		self.channel_state = np.zeros(CHANNEL_TAPS - 1, dtype=complex)
		if band.narrow_cutoff:
			self.narrow_taps = signal.firwin(CHANNEL_TAPS, band.narrow_cutoff, fs=MPX_RATE)
			self.narrow_state = np.zeros(CHANNEL_TAPS - 1, dtype=complex)
		self.last_sample = 1 + 0j
		self.dc_state = np.zeros(1)
		n = np.arange(PILOT_TAPS) - (PILOT_TAPS - 1) // 2
		self.pilot_taps = signal.firwin(PILOT_TAPS, PILOT_HALF_WIDTH, fs=MPX_RATE) * np.exp(2j * np.pi * PILOT_FREQ * n / MPX_RATE)
		self.pilot_state = np.zeros(PILOT_TAPS - 1, dtype=complex)
		self.pilot_delay = np.zeros((PILOT_TAPS - 1) // 2)
		self.audio_taps = signal.firwin(AUDIO_TAPS, band.audio_cutoff, fs=MPX_RATE)
		self.audio_state = np.zeros((2, AUDIO_TAPS - 1))
		alpha = np.exp(-1 / (AUDIO_RATE * band.deemphasis_tau)) if band.deemphasis_tau else 0
		self.deemphasis = ([1 - alpha], [1, -alpha])
		self.deemphasis_state = np.zeros((2, 1))
		freqs = np.fft.rfftfreq(BLOCK_SIZE // SDR_DECIMATION, 1 / MPX_RATE)
		self.pilot_bins = np.abs(freqs - PILOT_FREQ) < 2 * (freqs[1] - freqs[0])
		self.noise_bins = (freqs > PILOT_NOISE_BAND[0]) & (freqs < PILOT_NOISE_BAND[1])
		self.window = np.hanning(len(freqs) * 2 - 2)
		self.pilot_ratio = 0.0
		self.stereo = False
		self.signal_db = 0.0
		self.rds = RdsDecoder()

	def process(self, samples):
		floor, here, *neighbors = channel_powers(samples[:SCAN_SAMPLES], self.band)
		self.signal_db += SIGNAL_SMOOTHING * (10 * np.log10(here / floor) - self.signal_db)
		baseband = samples * self.mixer[:len(samples)]
		baseband, self.channel_state = signal.lfilter(self.channel_taps, 1, baseband, zi=self.channel_state)
		baseband = baseband[::SDR_DECIMATION]
		if self.band.narrow_cutoff:
			baseband, self.narrow_state = signal.lfilter(self.narrow_taps, 1, baseband, zi=self.narrow_state)
		if self.band.am:
			envelope = np.abs(baseband)
			mpx, self.dc_state = signal.lfilter([1, -1], [1, -DC_BLOCK_POLE], envelope / envelope.mean(), zi=self.dc_state)
		else:
			previous = np.concatenate(([self.last_sample], baseband[:-1]))
			self.last_sample = baseband[-1]
			mpx = np.angle(baseband * np.conj(previous)) * MPX_RATE / (2 * np.pi * self.band.max_deviation)
		if self.band.stereo:
			self.update_stereo(mpx)
		pilot, self.pilot_state = signal.lfilter(self.pilot_taps, 1, mpx, zi=self.pilot_state)
		delayed = np.concatenate((self.pilot_delay, mpx))
		self.pilot_delay = delayed[len(mpx):]
		delayed = delayed[:len(mpx)]
		# RDS takes its carrier and bit clock from the stereo pilot, so it only runs while there is one.
		if self.stereo:
			self.rds.process(mpx, pilot)
		else:
			self.rds.reset()
		# For a pilot of sin(t), the squared analytic pilot is -exp(2jt), so this gives the sin(2t) subcarrier.
		squared = pilot * pilot
		carrier = -np.imag(squared) / np.maximum(np.abs(squared), 1e-12)
		if self.stereo:
			stacked = np.vstack((delayed, 2 * delayed * carrier))
		else:
			stacked = np.vstack((delayed, np.zeros_like(delayed)))
		filtered, self.audio_state = signal.lfilter(self.audio_taps, 1, stacked, axis=1, zi=self.audio_state)
		mono, difference = filtered[:, ::AUDIO_DECIMATION]
		channels = np.vstack((mono + difference, mono - difference))
		channels, self.deemphasis_state = signal.lfilter(*self.deemphasis, channels, axis=1, zi=self.deemphasis_state)
		return channels.T

	def update_stereo(self, mpx):
		spectrum = np.abs(np.fft.rfft(mpx * self.window[:len(mpx)]))
		pilot = spectrum[self.pilot_bins].max()
		ratio = pilot / max(np.median(spectrum[self.noise_bins]), 1e-12)
		self.pilot_ratio += PILOT_SMOOTHING * (ratio - self.pilot_ratio)
		# A Hann windowed sine of amplitude A peaks at A * N / 4.
		level = 4 * pilot / len(mpx)
		self.stereo = bool(self.pilot_ratio > STEREO_THRESHOLD and level > PILOT_MIN_LEVEL)


class AudioBuffer:
	"""Holds stereo audio between the SDR thread and the sound card callback."""

	def __init__(self):
		self.lock = threading.Lock()
		self.clear()

	def clear(self):
		with self.lock:
			self.chunks = collections.deque()
			self.frames = 0
			self.filling = True

	def put(self, audio):
		with self.lock:
			self.chunks.append(audio)
			self.frames += len(audio)
			while self.frames > MAX_BUFFER_FRAMES:
				self.frames -= len(self.chunks.popleft())

	def cut(self, count):
		"""Fades the next count frames to silence and replaces the rest with silence, so the buffer holds exactly PREFILL_FRAMES."""
		kept = np.zeros((PREFILL_FRAMES, 2), dtype=np.float32)
		with self.lock:
			if self.chunks:
				old = np.concatenate(self.chunks)[:count]
				kept[:len(old)] = old * np.linspace(1, 0, len(old), dtype=np.float32)[:, None]
			self.chunks = collections.deque([kept])
			self.frames = PREFILL_FRAMES

	def get(self, count):
		out = np.zeros((count, 2), dtype=np.float32)
		with self.lock:
			if self.filling:
				if self.frames < PREFILL_FRAMES:
					return out
				self.filling = False
			filled = 0
			while filled < count and self.chunks:
				chunk = self.chunks[0]
				taken = min(count - filled, len(chunk))
				out[filled:filled + taken] = chunk[:taken]
				filled += taken
				self.frames -= taken
				if taken == len(chunk):
					self.chunks.popleft()
				else:
					self.chunks[0] = chunk[taken:]
			if filled < count:
				self.filling = True
		return out


@dataclass
class Device:
	index: int
	name: str
	serial: str


def list_devices():
	"""Returns the connected RTL-SDR dongles."""
	count = librtlsdr.rtlsdr_get_device_count()
	serials = RtlSdr.get_device_serial_addresses() if count else []
	return [Device(i, librtlsdr.rtlsdr_get_device_name(i).decode(errors="replace"), serial) for i, serial in zip(range(count), serials)]


class Receiver:
	"""Plays stereo FM from an RTL-SDR dongle through the default sound card.

	Call start() to begin playing and stop() when done. on_status_change, if set, is called with no arguments from a background thread when stereo, signal_db, rds_name, or rds_text changes."""

	def __init__(self, device_index, freq_mhz):
		self.sdr = RtlSdr(device_index=device_index)
		self.sdr.sample_rate = SDR_RATE
		self.sdr.gain = SDR_GAIN
		self.sdr_lock = threading.RLock()
		self.band = None
		self.demodulator = None
		self.raw_blocks = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)
		self.buffer = AudioBuffer()
		self.fade_in = np.concatenate((np.zeros(SETTLE_FRAMES), np.linspace(0, 1, FADE_FRAMES)))[:, None]
		self.tune_count = 0
		self.played_tune_count = 0
		self.freq_mhz = None
		self.volume_percent = DEFAULT_VOLUME
		self.is_paused = False
		self.muted = False
		self.stereo = False
		self.signal_db = 0
		self.rds_name = ""
		self.rds_text = ""
		self.on_status_change = None
		self.error = None
		self.running = True
		self.audio = pyaudio.PyAudio()
		self.stream = self.audio.open(format=pyaudio.paFloat32, channels=2, rate=AUDIO_RATE, output=True, stream_callback=self.fill_audio)
		self.tune(freq_mhz)
		self.threads = [threading.Thread(target=self.guard, args=(target,), daemon=True) for target in (self.read, self.demodulate)]

	@property
	def volume(self):
		return self.volume_percent

	@volume.setter
	def volume(self, percent):
		self.volume_percent = min(MAX_VOLUME, max(0, percent))

	@property
	def paused(self):
		return self.is_paused

	@paused.setter
	def paused(self, paused):
		self.is_paused = paused
		self.buffer.clear()

	def start(self):
		for thread in self.threads:
			thread.start()

	def tune(self, freq_mhz):
		band = band_for(freq_mhz)
		if band is None:
			raise ValueError(f"{freq_mhz} MHz is not in a supported band")
		freq_mhz = round(freq_mhz, 3)
		center_freq = round(freq_mhz * 1e6) - TUNE_OFFSET
		with self.sdr_lock:
			was_direct = bool(self.band and self.band.direct_sampling)
			if band.direct_sampling != was_direct:
				if was_direct:
					# Leaving direct sampling retunes to the current frequency, so it must be one the tuner can reach.
					self.sdr.center_freq = center_freq
				self.sdr.set_direct_sampling("q" if band.direct_sampling else 0)
				# Changing mode resets the tuner, including its gain.
				self.sdr.gain = SDR_GAIN
			self.band = band
			self.freq_mhz = freq_mhz
			self.sdr.center_freq = center_freq
			self.tune_count += 1

	def guard(self, target):
		try:
			target()
		except Exception as e:
			self.error = e
			self.running = False

	def read(self):
		# Only read here, so the next read starts right away and the dongle does not drop samples.
		while self.running:
			with self.sdr_lock:
				tune_count, band = self.tune_count, self.band
				raw = np.ctypeslib.as_array(self.sdr.read_bytes(BLOCK_SIZE * 2)).copy()
			try:
				self.raw_blocks.put_nowait((tune_count, band, raw))
			except queue.Full:
				pass

	def demodulate(self):
		while self.running:
			try:
				tune_count, band, raw = self.raw_blocks.get(timeout=QUEUE_TIMEOUT_SECONDS)
			except queue.Empty:
				continue
			if self.demodulator is None or band is not self.demodulator.band:
				self.demodulator = Demodulator(band)
			audio = self.demodulator.process(self.sdr.packed_bytes_to_iq(raw)).astype(np.float32)
			if tune_count != self.played_tune_count:
				self.played_tune_count = tune_count
				self.demodulator.rds.reset()
				self.buffer.cut(FADE_FRAMES)
				audio[:len(self.fade_in)] *= self.fade_in
			status = (self.demodulator.stereo, self.demodulator.rds.name, self.demodulator.rds.text)
			signal_db = self.demodulator.signal_db
			if status != (self.stereo, self.rds_name, self.rds_text) or abs(signal_db - self.signal_db) >= SIGNAL_HYSTERESIS_DB:
				(self.stereo, self.rds_name, self.rds_text), self.signal_db = status, round(signal_db)
				if self.on_status_change:
					self.on_status_change()
			if not self.is_paused:
				self.buffer.put(audio)
			self.raw_blocks.task_done()

	def fill_audio(self, in_data, frame_count, time_info, status):
		audio = self.buffer.get(frame_count)
		gain = 0 if self.muted or self.is_paused else self.volume_percent / MAX_VOLUME * OUTPUT_LEVEL
		return (audio * gain).tobytes(), pyaudio.paContinue

	def seek(self, direction):
		"""Tunes to the next station up (direction 1) or down (direction -1) in the current band, wrapping at the band edges.

		Blocks while scanning. Returns the new frequency, or None if no other station was found."""
		band = self.band
		count = round((band.max_mhz - band.min_mhz) / band.step_mhz) + 1
		start = round((self.freq_mhz - band.min_mhz) / band.step_mhz)
		channels = (round(band.min_mhz + (start + direction * i) % count * band.step_mhz, 3) for i in range(1, count))
		with self.sdr_lock:
			# Fade out the current station. Wait for the block being decoded first, or it would play after the fade.
			self.raw_blocks.join()
			self.buffer.cut(FADE_FRAMES)
			found = next((freq_mhz for freq_mhz in channels if self.has_station(freq_mhz, band)), None)
			# Tune before releasing the lock, so no block is read at the new frequency under the old tune count.
			self.tune(self.freq_mhz if found is None else found)
		return found

	def has_station(self, freq_mhz, band):
		"""Checks for a signal that is above the noise, stronger than the channels next to it, and not a sideband of a station two channels away. Call with sdr_lock held."""
		self.sdr.center_freq = round(freq_mhz * 1e6) - TUNE_OFFSET
		self.sdr.read_bytes(SCAN_SETTLE_BYTES)
		samples = self.sdr.packed_bytes_to_iq(self.sdr.read_bytes(SCAN_SAMPLES * 2))
		floor, here, below, above, two_below, two_above = channel_powers(samples, band)
		return here > floor * 10 ** (band.scan_threshold_db / 10) and here >= max(below, above) and here * SCAN_SIDEBAND_RATIO >= max(two_below, two_above)

	def stop(self):
		self.running = False
		for thread in self.threads:
			if thread.is_alive():
				thread.join()
		self.stream.stop_stream()
		self.stream.close()
		self.audio.terminate()
		self.sdr.close()


def menu(prompt, items):
	"""Constructs and shows a simple commandline menu.
	Returns an index of the provided items sequence."""
	for i in range(len(items)):
		print(str(i + 1) + ": " + items[i])
	result = None
	while True:
		result = input(prompt)
		try:
			result = int(result)
		except ValueError:
			print("error: Input must be a number. Please try again.")
			continue
		if result - 1 >= len(items) or result < 1:
			print("error: Provided option not in range. Please try again.")
			continue
		return result - 1


def read_key():
	import msvcrt
	if not msvcrt.kbhit():
		return None
	key = msvcrt.getwch()
	if key in ("\x00", "\xe0"):
		msvcrt.getwch()
		return None
	return key


def get_title():
	title = ctypes.create_unicode_buffer(TITLE_LENGTH)
	ctypes.windll.kernel32.GetConsoleTitleW(title, TITLE_LENGTH)
	return title.value


def set_title(title):
	ctypes.windll.kernel32.SetConsoleTitleW(title)


BAND_RANGES = " or ".join(f"{band.min_mhz} to {band.max_mhz}" for band in BANDS)


def choose_device(devices):
	if len(devices) == 1:
		return devices[0]
	return devices[menu("Choose a device: ", [f"{device.name} (serial {device.serial})" for device in devices])]


class RadioCLI:
	"""Keyboard controls and a status line for a Receiver."""

	def __init__(self, receiver):
		self.receiver = receiver
		self.receiver.on_status_change = self.show_status
		self.display_lock = threading.Lock()
		self.prompting = False
		self.show_signal = False

	def status_text(self):
		receiver = self.receiver
		parts = [f"{receiver.freq_mhz:.{receiver.band.digits}f} MHz", f"Signal {receiver.signal_db} dB" if self.show_signal else "", receiver.rds_name]
		if receiver.muted:
			parts.append("Muted")
		if receiver.paused:
			parts.append("Paused")
		parts.append(receiver.rds_text)
		return " | ".join(part for part in parts if part)

	def show_status(self):
		with self.display_lock:
			if self.prompting:
				return
			status = self.status_text()
			# Keep the line shorter than the console, or it wraps and \r no longer returns to its start.
			width = shutil.get_terminal_size().columns - 1
			sys.stdout.write("\r" + status[:width].ljust(width))
			sys.stdout.flush()
			set_title(status)

	def show_message(self, message):
		with self.display_lock:
			sys.stdout.write("\r" + message.ljust(60) + "\n")
		self.show_status()

	def prompt_frequency(self):
		with self.display_lock:
			self.prompting = True
			sys.stdout.write("\n")
		try:
			text = input(f"Frequency in MHz ({BAND_RANGES}): ")
		finally:
			self.prompting = False
		try:
			freq_mhz = float(text)
		except ValueError:
			self.show_message("error: Input must be a number.")
			return
		if band_for(freq_mhz) is None:
			self.show_message("error: Frequency not in range.")
			return
		self.receiver.tune(freq_mhz)
		self.show_status()

	def seek(self, direction):
		with self.display_lock:
			sys.stdout.write("\r" + "Scanning...".ljust(60))
			sys.stdout.flush()
		if self.receiver.seek(direction) is None:
			self.show_message("No other station found.")

	def step(self, direction):
		freq_mhz = self.receiver.freq_mhz + direction * self.receiver.band.step_mhz
		if band_for(freq_mhz) is self.receiver.band:
			self.receiver.tune(freq_mhz)

	def handle_key(self, key):
		receiver = self.receiver
		if key == " ":
			receiver.paused = not receiver.paused
		elif key == "_":
			receiver.volume -= VOLUME_STEP
		elif key == "+":
			receiver.volume += VOLUME_STEP
		elif key == "s":
			self.step(-1)
		elif key == "w":
			self.step(1)
		elif key == "S":
			self.seek(-1)
		elif key == "W":
			self.seek(1)
		elif key == "m":
			receiver.muted = not receiver.muted
		elif key == "i":
			self.show_signal = not self.show_signal
		elif key == "t":
			self.prompt_frequency()
			return
		self.show_status()

	def run(self):
		original_title = get_title()
		print("space: play/pause, _: volume down, +: volume up, s: back, w: forward, S: scan back, W: scan forward, t: enter frequency, m: mute, i: show/hide signal, Ctrl+C: quit")
		self.show_status()
		self.receiver.start()
		try:
			while self.receiver.running:
				key = read_key()
				if key is None:
					time.sleep(KEY_POLL_SECONDS)
				elif key == "\x03":
					break
				else:
					self.handle_key(key)
		except KeyboardInterrupt:
			pass
		finally:
			self.receiver.stop()
			set_title(original_title)
			print()


def main():
	parser = argparse.ArgumentParser(description="Listen to AM, FM, or NOAA weather radio with an RTL-SDR dongle.")
	parser.add_argument("frequency", type=float, nargs="?", default=FM.min_mhz, help=f"Frequency in MHz, AM, FM, or NOAA weather radio. Default is {FM.min_mhz}.")
	args = parser.parse_args()
	if band_for(args.frequency) is None:
		parser.error(f"frequency must be from {BAND_RANGES} MHz")
	devices = list_devices()
	if not devices:
		print("error: No RTL-SDR devices found.")
		return 1
	receiver = Receiver(choose_device(devices).index, args.frequency)
	RadioCLI(receiver).run()
	if receiver.error:
		print(f"error: {receiver.error}")
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
