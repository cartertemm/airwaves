import argparse
import collections
import os
import queue
import sys
import threading
import time

import numpy as np
import pyaudio
from scipy import signal

# This file shares its name with the pyrtlsdr package, so drop the script folder from the import path.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path = [path for path in sys.path if os.path.abspath(path or os.curdir) != SCRIPT_DIR]
from rtlsdr import RtlSdr
from rtlsdr.librtlsdr import librtlsdr

#MIN_FREQ_MHZ = 87.5
MAX_FREQ_MHZ = 1500.0
MIN_FREQ_MHZ = 0.0
#MAX_FREQ_MHZ = 108.0
FREQ_STEP_MHZ = 0.1
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

CHANNEL_CUTOFF = 120000
CHANNEL_TAPS = 151
MAX_DEVIATION = 75000
PILOT_FREQ = 19000
PILOT_HALF_WIDTH = 500
PILOT_TAPS = 201
AUDIO_CUTOFF = 15000
AUDIO_TAPS = 151
# North American de-emphasis. Europe uses 50 microseconds.
DEEMPHASIS_TAU = 75e-6
PILOT_NOISE_BAND = (16000, 18500)
STEREO_THRESHOLD = 10.0
# Stations send the pilot at about 0.1 of full deviation.
PILOT_MIN_LEVEL = 0.02
PILOT_SMOOTHING = 0.3
# The dongle delivers audio in bursts, so hold some back to keep the sound card fed between bursts.
PREFILL_FRAMES = AUDIO_RATE // 4
MAX_BUFFER_FRAMES = AUDIO_RATE
MAX_QUEUED_BLOCKS = 10
QUEUE_TIMEOUT_SECONDS = 0.5
# After a retune, the first 1 to 2 ms of samples are noise from the tuner settling.
SETTLE_FRAMES = AUDIO_RATE * 5 // 1000
FADE_FRAMES = AUDIO_RATE * 20 // 1000

KEY_POLL_SECONDS = 0.02


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


class StereoFMDemodulator:
	"""Turns blocks of raw IQ samples at SDR_RATE into stereo audio at AUDIO_RATE."""

	def __init__(self):
		n = np.arange(BLOCK_SIZE)
		self.mixer = np.exp(-2j * np.pi * TUNE_OFFSET * n / SDR_RATE)
		self.channel_taps = signal.firwin(CHANNEL_TAPS, CHANNEL_CUTOFF, fs=SDR_RATE)
		self.channel_state = np.zeros(CHANNEL_TAPS - 1, dtype=complex)
		self.last_sample = 1 + 0j
		n = np.arange(PILOT_TAPS) - (PILOT_TAPS - 1) // 2
		self.pilot_taps = signal.firwin(PILOT_TAPS, PILOT_HALF_WIDTH, fs=MPX_RATE) * np.exp(2j * np.pi * PILOT_FREQ * n / MPX_RATE)
		self.pilot_state = np.zeros(PILOT_TAPS - 1, dtype=complex)
		self.pilot_delay = np.zeros((PILOT_TAPS - 1) // 2)
		self.audio_taps = signal.firwin(AUDIO_TAPS, AUDIO_CUTOFF, fs=MPX_RATE)
		self.audio_state = np.zeros((2, AUDIO_TAPS - 1))
		alpha = np.exp(-1 / (AUDIO_RATE * DEEMPHASIS_TAU))
		self.deemphasis = ([1 - alpha], [1, -alpha])
		self.deemphasis_state = np.zeros((2, 1))
		freqs = np.fft.rfftfreq(BLOCK_SIZE // SDR_DECIMATION, 1 / MPX_RATE)
		self.pilot_bins = np.abs(freqs - PILOT_FREQ) < 2 * (freqs[1] - freqs[0])
		self.noise_bins = (freqs > PILOT_NOISE_BAND[0]) & (freqs < PILOT_NOISE_BAND[1])
		self.window = np.hanning(len(freqs) * 2 - 2)
		self.pilot_ratio = 0.0
		self.stereo = False

	def process(self, samples):
		baseband = samples * self.mixer[:len(samples)]
		baseband, self.channel_state = signal.lfilter(self.channel_taps, 1, baseband, zi=self.channel_state)
		baseband = baseband[::SDR_DECIMATION]
		previous = np.concatenate(([self.last_sample], baseband[:-1]))
		self.last_sample = baseband[-1]
		mpx = np.angle(baseband * np.conj(previous)) * MPX_RATE / (2 * np.pi * MAX_DEVIATION)
		self.update_stereo(mpx)
		pilot, self.pilot_state = signal.lfilter(self.pilot_taps, 1, mpx, zi=self.pilot_state)
		delayed = np.concatenate((self.pilot_delay, mpx))
		self.pilot_delay = delayed[len(mpx):]
		delayed = delayed[:len(mpx)]
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
		self.stereo = self.pilot_ratio > STEREO_THRESHOLD and level > PILOT_MIN_LEVEL


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


class Receiver:
	def __init__(self, device_index, freq_mhz):
		self.sdr = RtlSdr(device_index=device_index)
		self.sdr.sample_rate = SDR_RATE
		self.sdr.gain = "auto"
		self.sdr_lock = threading.Lock()
		self.display_lock = threading.Lock()
		self.demodulator = StereoFMDemodulator()
		self.raw_blocks = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)
		self.buffer = AudioBuffer()
		self.fade_in = np.concatenate((np.zeros(SETTLE_FRAMES), np.linspace(0, 1, FADE_FRAMES)))[:, None]
		self.tune_count = 0
		self.played_tune_count = 0
		self.freq_mhz = None
		self.volume = DEFAULT_VOLUME
		self.paused = False
		self.muted = False
		self.prompting = False
		self.stereo_shown = False
		self.error = None
		self.running = True
		self.audio = pyaudio.PyAudio()
		self.stream = self.audio.open(format=pyaudio.paFloat32, channels=2, rate=AUDIO_RATE, output=True, stream_callback=self.play)
		self.tune(freq_mhz)
		self.threads = [threading.Thread(target=self.guard, args=(target,), daemon=True) for target in (self.read, self.demodulate)]

	def start(self):
		for thread in self.threads:
			thread.start()

	def tune(self, freq_mhz):
		self.freq_mhz = round(freq_mhz, 1)
		with self.sdr_lock:
			self.sdr.center_freq = int(self.freq_mhz * 1e6) - TUNE_OFFSET
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
				tune_count = self.tune_count
				raw = np.ctypeslib.as_array(self.sdr.read_bytes(BLOCK_SIZE * 2)).copy()
			try:
				self.raw_blocks.put_nowait((tune_count, raw))
			except queue.Full:
				pass

	def demodulate(self):
		while self.running:
			try:
				tune_count, raw = self.raw_blocks.get(timeout=QUEUE_TIMEOUT_SECONDS)
			except queue.Empty:
				continue
			audio = self.demodulator.process(self.sdr.packed_bytes_to_iq(raw)).astype(np.float32)
			if tune_count != self.played_tune_count:
				self.played_tune_count = tune_count
				self.buffer.cut(FADE_FRAMES)
				audio[:len(self.fade_in)] *= self.fade_in
			if self.demodulator.stereo != self.stereo_shown:
				self.stereo_shown = self.demodulator.stereo
				self.show_status()
			if not self.paused:
				self.buffer.put(audio)

	def play(self, in_data, frame_count, time_info, status):
		audio = self.buffer.get(frame_count)
		gain = 0 if self.muted or self.paused else self.volume / MAX_VOLUME * OUTPUT_LEVEL
		return (audio * gain).tobytes(), pyaudio.paContinue

	def status_text(self):
		parts = [f"{self.freq_mhz:.1f} MHz", "Stereo" if self.stereo_shown else "Mono", f"Volume {self.volume}%"]
		if self.muted:
			parts.append("Muted")
		if self.paused:
			parts.append("Paused")
		return " | ".join(parts)

	def show_status(self):
		with self.display_lock:
			if self.prompting:
				return
			sys.stdout.write("\r" + self.status_text().ljust(60))
			sys.stdout.flush()

	def show_message(self, message):
		with self.display_lock:
			sys.stdout.write("\r" + message.ljust(60) + "\n")
		self.show_status()

	def prompt_frequency(self):
		with self.display_lock:
			self.prompting = True
			sys.stdout.write("\n")
		try:
			text = input(f"Frequency in MHz ({MIN_FREQ_MHZ} to {MAX_FREQ_MHZ}): ")
		finally:
			self.prompting = False
		try:
			freq_mhz = float(text)
		except ValueError:
			self.show_message("error: Input must be a number.")
			return
		if not MIN_FREQ_MHZ <= freq_mhz <= MAX_FREQ_MHZ:
			self.show_message("error: Frequency not in range.")
			return
		self.tune(freq_mhz)
		self.show_status()

	def step(self, direction):
		freq_mhz = self.freq_mhz + direction * FREQ_STEP_MHZ
		if MIN_FREQ_MHZ <= round(freq_mhz, 1) <= MAX_FREQ_MHZ:
			self.tune(freq_mhz)

	def handle_key(self, key):
		if key == " ":
			self.paused = not self.paused
			self.buffer.clear()
		elif key == "_":
			self.volume = max(0, self.volume - VOLUME_STEP)
		elif key == "+":
			self.volume = min(MAX_VOLUME, self.volume + VOLUME_STEP)
		elif key == "s":
			self.step(-1)
		elif key == "w":
			self.step(1)
		elif key == "m":
			self.muted = not self.muted
		elif key == "t":
			self.prompt_frequency()
			return
		self.show_status()

	def close(self):
		self.running = False
		for thread in self.threads:
			if thread.is_alive():
				thread.join()
		self.stream.stop_stream()
		self.stream.close()
		self.audio.terminate()
		self.sdr.close()


def read_key():
	import msvcrt
	if not msvcrt.kbhit():
		return None
	key = msvcrt.getwch()
	if key in ("\x00", "\xe0"):
		msvcrt.getwch()
		return None
	return key


def choose_device():
	count = librtlsdr.rtlsdr_get_device_count()
	if count == 0:
		return None
	if count == 1:
		return 0
	names = [librtlsdr.rtlsdr_get_device_name(i).decode(errors="replace") for i in range(count)]
	serials = RtlSdr.get_device_serial_addresses()
	items = [f"{name} (serial {serial})" for name, serial in zip(names, serials)]
	return menu("Choose a device: ", items)


def main():
	parser = argparse.ArgumentParser(description="Listen to FM radio with an RTL-SDR dongle.")
	parser.add_argument("frequency", type=float, nargs="?", default=MIN_FREQ_MHZ, help=f"Frequency in MHz. Default is {MIN_FREQ_MHZ}.")
	args = parser.parse_args()
	if not MIN_FREQ_MHZ <= args.frequency <= MAX_FREQ_MHZ:
		parser.error(f"frequency must be from {MIN_FREQ_MHZ} to {MAX_FREQ_MHZ} MHz")
	device_index = choose_device()
	if device_index is None:
		print("error: No RTL-SDR devices found.")
		return 1
	receiver = Receiver(device_index, args.frequency)
	print("space: play/pause, _: volume down, +: volume up, s: back, w: forward, t: enter frequency, m: mute, Ctrl+C: quit")
	receiver.show_status()
	receiver.start()
	try:
		while receiver.running:
			key = read_key()
			if key is None:
				time.sleep(KEY_POLL_SECONDS)
			elif key == "\x03":
				break
			else:
				receiver.handle_key(key)
	except KeyboardInterrupt:
		pass
	finally:
		receiver.close()
		print()
	if receiver.error:
		print(f"error: {receiver.error}")
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
