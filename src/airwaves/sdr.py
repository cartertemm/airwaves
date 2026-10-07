import argparse
import cmath
import collections
import contextlib
import ctypes
import locale
import logging
import math
import os
import queue
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, replace
from functools import partial
from datetime import datetime, timedelta, timezone

import numpy as np
import pyaudio

if sys.platform == "win32":
	import msvcrt
	# pyrtlsdr loads the osmocom driver (rtlsdr.dll) from the package folder.
	os.add_dll_directory(os.path.dirname(__file__))
	# Python's console stderr keeps writing to this handle, even after fd 2 changes.
	STDERR_HANDLE = ctypes.c_void_p(msvcrt.get_osfhandle(2))
from rtlsdr import RtlSdr
from rtlsdr.librtlsdr import librtlsdr
from rtlsdr.rtlsdr import LibUSBError

from . import flight_log, nrsc5

VERSION = "0.2"
VERSION_TEXT = f"SDR Tuner version {VERSION}"
VOLUME_STEP = 10
DEFAULT_VOLUME = 50
MAX_VOLUME = 100
# Station audio peaks near full scale, leave headroom for the sound card.
OUTPUT_LEVEL = 0.5

SDR_RATE = 1440000
# A loud stereo signal is about 256 kHz wide.
MPX_RATE = 288000
AUDIO_RATE = 48000
HD_AUDIO_RATE = 44100
PCM_SCALE = 32768
# A station with HD Radio locks in about 1 second.
HD_LOCK_SECONDS = 3
HD_IDLE_SECONDS = 0.05
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
# Removes the AM carrier level, or everything below about 20 Hz.
DC_BLOCK_POLE = 1 - 2 * np.pi * 20 / MPX_RATE
# De-emphasis runs as a filter of this many taps. Its response falls below 1e-15 well within them.
DEEMPHASIS_TAPS = 128
RDS_FREQ = 57000
RDS_HALF_WIDTH = 2400
# The RDS bit clock is the pilot divided by 16 - so one bit lasts 16 pilot cycles.
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
# SAME alert headers on NOAA weather radio: frequency shift keying at 520.83 bits per second.
SAME_BAUD = 520 + 5 / 6
SAME_MARK = 4 * SAME_BAUD
SAME_SPACE = 3 * SAME_BAUD
SAME_DECIMATION = 4
SAME_PLL_GAIN = 0.2
# "ZCZC" with the bytes in the order they arrive, least significant bit first.
SAME_START = 0x435A435A
SAME_MAX_LENGTH = 268
SAME_HEADER = re.compile(r"ZCZC-([A-Z]{3})-([A-Z]{3})-(\d{6}(?:-\d{6})*)\+(\d{2})(\d{2})-(\d{3})(\d{2})(\d{2})-([^-]{1,8})-")
SAME_EVENTS = {
	"ADR": "Administrative Message", "AVA": "Avalanche Watch", "AVW": "Avalanche Warning", "BLU": "Blue Alert",
	"BZW": "Blizzard Warning", "CAE": "Child Abduction Emergency", "CDW": "Civil Danger Warning", "CEM": "Civil Emergency Message",
	"CFA": "Coastal Flood Watch", "CFW": "Coastal Flood Warning", "DMO": "Practice/Demo Warning", "DSW": "Dust Storm Warning",
	"EAN": "Emergency Action Notification", "EQW": "Earthquake Warning", "EVI": "Evacuation Immediate", "EWW": "Extreme Wind Warning",
	"FFA": "Flash Flood Watch", "FFS": "Flash Flood Statement", "FFW": "Flash Flood Warning", "FLA": "Flood Watch",
	"FLS": "Flood Statement", "FLW": "Flood Warning", "FRW": "Fire Warning", "HLS": "Hurricane Local Statement",
	"HMW": "Hazardous Materials Warning", "HUA": "Hurricane Watch", "HUW": "Hurricane Warning", "HWA": "High Wind Watch",
	"HWW": "High Wind Warning", "LAE": "Local Area Emergency", "LEW": "Law Enforcement Warning", "NIC": "National Information Center",
	"NMN": "Network Message Notification", "NPT": "National Periodic Test", "NUW": "Nuclear Power Plant Warning", "RHW": "Radiological Hazard Warning",
	"RMT": "Required Monthly Test", "RWT": "Required Weekly Test", "SMW": "Special Marine Warning", "SPS": "Special Weather Statement",
	"SPW": "Shelter in Place Warning", "SQW": "Snow Squall Warning", "SSA": "Storm Surge Watch", "SSW": "Storm Surge Warning",
	"SVA": "Severe Thunderstorm Watch", "SVR": "Severe Thunderstorm Warning", "SVS": "Severe Weather Statement", "TOA": "Tornado Watch",
	"TOE": "911 Telephone Outage Emergency", "TOR": "Tornado Warning", "TRA": "Tropical Storm Watch", "TRW": "Tropical Storm Warning",
	"TSA": "Tsunami Watch", "TSW": "Tsunami Warning", "VOW": "Volcano Warning", "WSA": "Winter Storm Watch", "WSW": "Winter Storm Warning",
}
ALARM_FREQ = 1050
# The share of the audio power that must be at the alarm frequency.
ALARM_RATIO = 0.6
ALARM_SECONDS = 1
# A tone this soon after a SAME header belongs to that header's alert.
ALARM_AFTER_HEADER_SECONDS = 30
ALARM_SHOW_MINUTES = 10
# ACARS: text messages between aircraft and the ground, sent as 2400 bit per second MSK over AM.
# Each channel is averaged down to ACARS_CHANNEL_RATE, then filtered and decimated to ACARS_RATE. The filter keeps out the channels 25 kHz away.
ACARS_CHANNEL_RATE = 144000
ACARS_RATE = 12000
ACARS_CHANNEL_DECIMATION = SDR_RATE // ACARS_CHANNEL_RATE
ACARS_DECIMATION = ACARS_CHANNEL_RATE // ACARS_RATE
ACARS_CUTOFF = 4500
ACARS_TAPS = 101
# MSK shifts between 1200 and 2400 Hz. The demodulator mixes the tones down from their center, 1800 Hz.
ACARS_TONE_STEP = 2 * np.pi * 1800 / ACARS_RATE
# The mixer phase moves 3/2 pi in one bit.
ACARS_BIT_PHASE = 3 * np.pi / 2
# The matched filter spans two bits, and has ACARS_OVERSAMPLING versions to match where the bit lands between samples.
ACARS_FILTER_LENGTH = ACARS_RATE // 1200 + 1
ACARS_OVERSAMPLING = 12
ACARS_PLL_GAIN = 38e-4
ACARS_PLL_SMOOTHING = 0.52
ACARS_SYN = 0x16
ACARS_SOH = 0x01
ACARS_STX = 0x02
# Bytes carry odd parity in the top bit, so these are ETX and ETB with the parity bit set.
ACARS_ETX = 0x83
ACARS_ETB = 0x97
ACARS_DEL = 0x7F
# A header is mode, registration (7), acknowledgment, label (2), block ID, then STX or ETX.
ACARS_HEADER_LENGTH = 13
ACARS_MAX_LENGTH = 240
ACARS_CRC_POLYNOMIAL = 0x8408
# Messages from aircraft start their text with a 4 character message number and a 6 character flight number.
ACARS_NUMBER_LENGTH = 4
ACARS_FLIGHT_LENGTH = 6
# The dongle delivers audio in bursts. Hold some back to keep the sound card fed between bursts.
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
# Skip the tuner noise after each retune while scanning.
SCAN_SETTLE_BYTES = 8192
SCAN_SIDEBAND_RATIO = 10 ** (10 / 10)
SCAN_LOW_OFFSET = 100000
SCAN_HIGH_OFFSET = 600000

KEY_POLL_SECONDS = 0.02
HELP_KEYS = ("space: play/pause", "_: volume down", "+: volume up", "s: back", "w: forward", "S: scan back", "W: scan forward", "t: enter frequency", "m: mute", "i: show/hide signal", "d: next HD channel", "D: previous HD channel", "a: ACARS on/off", "c: cast to Sonos or AirPlay", "h: help", "Ctrl+C: quit")
HELP_KEYS_PER_LINE = 3
CAST_KINDS = ("sonos", "airplay")
HELP_TEXT = "\n".join(", ".join(HELP_KEYS[i:i + HELP_KEYS_PER_LINE]) for i in range(0, len(HELP_KEYS), HELP_KEYS_PER_LINE))
TITLE_LENGTH = 1024
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
WM_HOTKEY = 0x0312
HANDLE_FLAG_PROTECT_FROM_CLOSE = 0x2


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
	khz: bool = False
	# Weather radio emits SAME alert headers and the 1050 Hz alarm tone.
	alerts: bool = False
	# FM stations can send HD Radio (NRSC-5) channels beside the analog signal.
	hd: bool = False
	# Channels decoded as ACARS. The capture centers between the lowest and highest.
	acars_channels: tuple = ()

	def format(self, freq_mhz):
		return f"{freq_mhz * 1000:.0f} kHz" if self.khz else f"{freq_mhz:.{self.digits}f} MHz"

	@property
	def half_width(self):
		"""Half the width of the frequency range measured for one channel."""
		return self.narrow_cutoff or self.step_mhz * 1e6 / 2

	@property
	def acars_center(self):
		"""The capture center in Hz for the ACARS channels."""
		return round((self.min_mhz + self.max_mhz) / 2 * 1e6)


FM = Band(min_mhz=87.5, max_mhz=108.0, step_mhz=0.1, digits=1, max_deviation=75000, narrow_cutoff=None, audio_cutoff=15000, stereo=True, deemphasis_tau=75e-6, hd=True)
NOAA = Band(min_mhz=162.4, max_mhz=162.55, step_mhz=0.025, digits=3, max_deviation=5000, narrow_cutoff=8000, audio_cutoff=4000, stereo=False, deemphasis_tau=None, alerts=True)
AM = Band(min_mhz=0.53, max_mhz=1.7, step_mhz=0.01, digits=2, max_deviation=None, narrow_cutoff=5000, audio_cutoff=5000, stereo=False, deemphasis_tau=None, am=True, direct_sampling=True, scan_threshold_db=13, khz=True)
# Direct sampling stops at 14.4 MHz, half of the dongle's 28.8 MHz converter rate.
SW = Band(min_mhz=2.3, max_mhz=14.4, step_mhz=0.005, digits=3, max_deviation=None, narrow_cutoff=4500, audio_cutoff=4500, stereo=False, deemphasis_tau=None, am=True, direct_sampling=True, scan_threshold_db=13)
AIR = Band(min_mhz=118.0, max_mhz=136.975, step_mhz=0.025, digits=3, max_deviation=None, narrow_cutoff=8000, audio_cutoff=4000, stereo=False, deemphasis_tau=None, am=True)
# Europe uses 50 microsecond de-emphasis, a 9 kHz AM channel grid, and has no NOAA weather radio.
FM_EU = replace(FM, deemphasis_tau=50e-6)
AM_EU = replace(AM, min_mhz=0.531, max_mhz=1.602, step_mhz=0.009)
REGIONS = {"us": (AM, SW, FM, AIR, NOAA), "eu": (AM_EU, SW, FM_EU, AIR)}
# Only channels that fit in one SDR_RATE capture. The US also uses 129.125 and 130.025 MHz.
ACARS = replace(AIR, min_mhz=130.425, max_mhz=131.55, acars_channels=(130.425, 130.45, 131.125, 131.55))
ACARS_EU = replace(AIR, min_mhz=131.525, max_mhz=131.825, acars_channels=(131.525, 131.725, 131.825))
ACARS_BANDS = {"us": ACARS, "eu": ACARS_EU}
EUROPE_COUNTRIES = {"AD", "AL", "AT", "BA", "BE", "BG", "BY", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FO", "FR", "GB", "GI", "GR", "HR", "HU", "IE", "IM", "IS", "IT", "LI", "LT", "LU", "LV", "MC", "MD", "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS", "RU", "SE", "SI", "SK", "SM", "UA", "VA", "XK"}
GEO_NAME_LENGTH = 16


def band_for(freq_mhz, bands):
	"""Returns the band in bands that holds freq_mhz, or None."""
	return next((band for band in bands if band.min_mhz <= round(freq_mhz, 3) <= band.max_mhz), None)


def detect_region():
	"""Guesses "eu" or "us" from the system's country setting, and falls back to "us"."""
	if sys.platform == "win32":
		country = ctypes.create_unicode_buffer(GEO_NAME_LENGTH)
		ctypes.windll.kernel32.GetUserDefaultGeoName(country, GEO_NAME_LENGTH)
		country = country.value
	else:
		# Locales look like en_GB.UTF-8, or C when no country is set.
		country = (locale.getlocale()[0] or "").partition("_")[2]
	return "eu" if country.upper() in EUROPE_COUNTRIES else "us"


def fir_taps(count, low, high, rate):
	"""Returns Hamming windowed taps that pass low to high Hz, with a gain of 1 at the band center. A low of 0 gives a low-pass filter with a gain of 1 at 0 Hz."""
	n = np.arange(count) - (count - 1) / 2
	taps = (2 * high / rate) * np.sinc(2 * high * n / rate) - (2 * low / rate) * np.sinc(2 * low * n / rate)
	taps *= np.hamming(count)
	center = (low + high) / 2 if low else 0
	return taps / np.sum(taps * np.cos(2 * np.pi * center * n / rate))


def fir_filter(taps, samples, history):
	"""Filters samples, or each row of samples, with taps. history holds the last len(taps) - 1 samples of the previous call, and the new history is returned."""
	padded = np.concatenate((history, samples), axis=-1)
	if padded.ndim == 1:
		filtered = np.convolve(padded, taps, "valid")
	else:
		filtered = np.array([np.convolve(row, taps, "valid") for row in padded])
	return filtered, padded[..., samples.shape[-1]:]


def dc_block(samples, state):
	"""Removes the DC from samples with a one-pole high-pass filter. state is the last input and output of the previous call, and the new state is returned."""
	last_input, last_output = state
	difference = samples - np.concatenate(([last_input], samples[:-1]))
	# Solves output[n] = difference[n] + DC_BLOCK_POLE * output[n - 1] without a loop.
	powers = DC_BLOCK_POLE ** np.arange(1, len(samples) + 1)
	output = powers * (last_output + np.cumsum(difference / powers))
	return output, (samples[-1], output[-1])


class Spectrum:
	"""The power spectrum of one capture, used to measure channels in it."""

	def __init__(self, samples):
		self.power = np.abs(np.fft.fft(samples * np.hanning(len(samples)))) ** 2
		self.freqs = np.fft.fftfreq(len(samples), 1 / SDR_RATE)
		self.floor = np.median(self.power)

	def channel_powers(self, offset, band):
		"""Returns the power in the channel at offset from the capture center, then in the channels one and two steps below and above it."""
		step = band.step_mhz * 1e6
		return [self.power[np.abs(self.freqs - offset - shift) < band.half_width].mean() for shift in (0, -step, step, -2 * step, 2 * step)]


def has_station(spectrum, offset, band):
	"""Checks for a signal that is above the noise, stronger than the channels next to it, and not a sideband of a station two channels away."""
	here, below, above, two_below, two_above = spectrum.channel_powers(offset, band)
	return here > spectrum.floor * 10 ** (band.scan_threshold_db / 10) and here >= max(below, above) and here * SCAN_SIDEBAND_RATIO >= max(two_below, two_above)


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


@dataclass
class Alert:
	name: str
	event: str = ""
	locations: tuple = ()
	issued: datetime | None = None
	expires: datetime | None = None
	sender: str = ""

	def applies_to(self, county):
		"""Checks a 5 or 6 digit county FIPS code against the alert's areas. A county of None, or an alert without areas, always matches."""
		if not county or not self.locations:
			return True
		state, county = county[-5:-3], county[-3:]
		return any(location[1:3] == state and location[3:] in ("000", county) for location in self.locations)

	def active(self):
		return self.expires is None or datetime.now(timezone.utc) < self.expires

	def describe(self):
		text = f"ALERT: {self.name}"
		if self.expires:
			text += " until " + self.expires.astimezone().strftime("%I:%M %p").lstrip("0")
		if self.locations:
			text += " for " + ", ".join(self.locations)
		return text


def parse_same(text):
	"""Returns the Alert in a SAME header, or None if text does not hold one."""
	match = SAME_HEADER.search(text)
	if match is None:
		return None
	sender, event, locations, hours, minutes, day, hour, minute, station = match.groups()
	year_start = datetime(datetime.now(timezone.utc).year, 1, 1, tzinfo=timezone.utc)
	issued = year_start + timedelta(days=int(day) - 1, hours=int(hour), minutes=int(minute))
	return Alert(SAME_EVENTS.get(event, event), event, tuple(locations.split("-")), issued, issued + timedelta(hours=int(hours), minutes=int(minutes)), f"{sender} {station}")


class AlertDecoder:
	"""Finds SAME alert headers and the 1050 Hz alarm tone in weather radio audio."""

	def __init__(self):
		self.bit_samples = round(AUDIO_RATE / SAME_BAUD)
		self.new = []
		self.reset()

	def reset(self):
		self.sample_index = 0
		self.filter_state = np.zeros((2, self.bit_samples - 1), dtype=complex)
		self.phase = 0.0
		self.last_sign = False
		self.register = 0
		self.text = None
		self.bit_count = 0
		self.candidates = set()
		self.reported = set()
		self.seconds = 0.0
		self.header_seconds = None
		self.tone_seconds = 0.0

	def process(self, audio):
		self.seconds += len(audio) / AUDIO_RATE
		self.check_tone(audio)
		n = self.sample_index + np.arange(len(audio))
		self.sample_index += len(audio)
		mixed = audio * np.exp(-2j * np.pi * np.outer((SAME_MARK, SAME_SPACE), n) / AUDIO_RATE)
		tones, self.filter_state = fir_filter(np.ones(self.bit_samples) / self.bit_samples, mixed, self.filter_state)
		# Positive where the mark tone, a 1 bit, is stronger.
		soft = (np.abs(tones[0]) ** 2 - np.abs(tones[1]) ** 2)[::SAME_DECIMATION]
		step = SAME_BAUD * SAME_DECIMATION / AUDIO_RATE
		for value in soft:
			sign = value > 0
			if sign != self.last_sign:
				# Bits change at the bit boundary, so pull the bit clock toward each change.
				self.last_sign = sign
				self.phase -= SAME_PLL_GAIN * (self.phase if self.phase < 0.5 else self.phase - 1)
			before = self.phase
			self.phase += step
			if before < 0.5 <= self.phase:
				self.receive_bit(int(sign))
			if self.phase >= 1:
				self.phase -= 1

	def receive_bit(self, bit):
		self.register = (self.register >> 1) | (bit << 31)
		if self.text is None:
			if self.register == SAME_START:
				self.text = "ZCZC"
				self.bit_count = 0
			return
		self.bit_count += 1
		if self.bit_count < 8:
			return
		self.bit_count = 0
		byte = self.register >> 24
		if 0x20 <= byte < 0x7F and len(self.text) < SAME_MAX_LENGTH:
			self.text += chr(byte)
			return
		self.receive_header(self.text)
		self.text = None

	def receive_header(self, text):
		match = SAME_HEADER.search(text)
		if match is None:
			return
		header = match.group(0)
		self.header_seconds = self.seconds
		# Each header is sent three times. Report it only once two copies match.
		if header in self.reported:
			return
		if header not in self.candidates:
			self.candidates.add(header)
			return
		self.reported.add(header)
		self.new.append(parse_same(header))

	def check_tone(self, audio):
		n = np.arange(len(audio))
		tone = 2 * np.abs(np.dot(audio, np.exp(-2j * np.pi * ALARM_FREQ * n / AUDIO_RATE))) ** 2 / len(audio) ** 2
		if tone < ALARM_RATIO * max(np.mean(audio ** 2), 1e-12):
			self.tone_seconds = 0.0
			return
		before = self.tone_seconds
		self.tone_seconds += len(audio) / AUDIO_RATE
		after_header = self.header_seconds is not None and self.seconds - self.header_seconds < ALARM_AFTER_HEADER_SECONDS
		if before < ALARM_SECONDS <= self.tone_seconds and not after_header:
			now = datetime.now(timezone.utc)
			self.new.append(Alert("Warning alarm tone", issued=now, expires=now + timedelta(minutes=ALARM_SHOW_MINUTES)))


def acars_crc(data):
	"""Returns the CRC-16 (KERMIT) of data. It is 0 over a block followed by its two CRC bytes."""
	crc = 0
	for byte in data:
		crc ^= byte
		for _ in range(8):
			crc = (crc >> 1) ^ (ACARS_CRC_POLYNOMIAL if crc & 1 else 0)
	return crc


def odd_parity(byte):
	return bin(byte).count("1") % 2 == 1


@dataclass
class AcarsMessage:
	freq_mhz: float
	mode: str
	registration: str
	label: str
	block_id: str
	text: str
	flight: str = ""
	number: str = ""
	time: datetime = None

	def describe(self):
		parts = [self.time.astimezone().strftime("%H:%M"), f"{self.freq_mhz:.3f}", self.flight, self.registration]
		return " ".join(part for part in parts if part) + ": " + " ".join(self.text.split())


def parse_acars(freq_mhz, block):
	"""Returns the AcarsMessage in block, the bytes from the mode to ETX or ETB with parity removed."""
	text = block[1:].decode("ascii")
	mode, registration, label, block_id, start = chr(block[0]), text[:7], text[8:10], text[10], text[11]
	# Aircraft send DEL as the second label character of a link test, shown as "d".
	label = label.replace(chr(ACARS_DEL), "d")
	body = text[12:-1] if start == chr(ACARS_STX) else ""
	message = AcarsMessage(freq_mhz, mode, registration.replace(".", ""), label, block_id, body, time=datetime.now(timezone.utc))
	if body and block_id.isdigit():
		number_end = ACARS_NUMBER_LENGTH
		flight_end = number_end + ACARS_FLIGHT_LENGTH
		message.number, message.flight, message.text = body[:number_end], body[number_end:flight_end].strip(), body[flight_end:]
	return message


class AcarsDecoder:
	"""Decodes ACARS messages on one channel from raw IQ samples at SDR_RATE. offset is the channel's distance in Hz from the capture center.

	The MSK demodulator follows acarsdec's: it mixes the AM audio down from 1800 Hz, and one loop keeps the mixer and the bit clock locked to the signal."""

	def __init__(self, freq_mhz, offset):
		self.freq_mhz = freq_mhz
		self.offset = offset
		self.sample_index = 0
		self.mixer = np.exp(-2j * np.pi * offset * np.arange(BLOCK_SIZE) / SDR_RATE)
		self.channel_taps = fir_taps(ACARS_TAPS, 0, ACARS_CUTOFF, ACARS_CHANNEL_RATE)
		self.channel_state = np.zeros(ACARS_TAPS - 1, dtype=complex)
		self.audio_index = 0
		count = ACARS_FILTER_LENGTH * ACARS_OVERSAMPLING + 1
		# A half cosine, the shape of one MSK bit.
		shape = np.maximum(np.cos(2 * np.pi * 600 / ACARS_RATE / ACARS_OVERSAMPLING * (np.arange(count) - (count - 1) / 2)), 0)
		self.matched = [shape[start::ACARS_OVERSAMPLING][:ACARS_FILTER_LENGTH] for start in range(ACARS_OVERSAMPLING + 1)]
		self.history = np.zeros(ACARS_FILTER_LENGTH - 1, dtype=complex)
		self.clock = 0.0
		self.drift_phase = 0.0
		self.symbol = 0
		self.register = 0
		self.new = []
		self.reset()

	def reset(self):
		self.state = "sync"
		self.drift = 0.0
		self.bits_left = 1
		self.block = bytearray()

	def process(self, samples):
		# The mixer repeats every second, so the index stays small.
		start = cmath.exp(-2j * np.pi * self.offset * self.sample_index / SDR_RATE)
		self.sample_index = (self.sample_index + len(samples)) % SDR_RATE
		channel = (samples * self.mixer[:len(samples)] * start).reshape(-1, ACARS_CHANNEL_DECIMATION).mean(axis=1)
		channel, self.channel_state = fir_filter(self.channel_taps, channel, self.channel_state)
		envelope = np.abs(channel[::ACARS_DECIMATION])
		self.demodulate(envelope - envelope.mean())

	def demodulate(self, audio):
		n = self.audio_index + np.arange(len(audio))
		self.audio_index = (self.audio_index + len(audio)) % ACARS_RATE
		mixed = np.concatenate((self.history, audio * np.exp(-1j * ACARS_TONE_STEP * n)))
		self.history = mixed[len(mixed) - len(self.history):]
		position = len(self.history) - 1
		end = len(mixed) - 1
		while True:
			step = ACARS_TONE_STEP + self.drift
			wait = max(1, math.ceil((ACARS_BIT_PHASE - step / 2 - self.clock) / step))
			if position + wait > end:
				wait = end - position
				self.clock += wait * step
				self.drift_phase += wait * self.drift
				return
			position += wait
			self.clock += wait * step - ACARS_BIT_PHASE
			self.drift_phase += wait * self.drift
			offset = min(ACARS_OVERSAMPLING, int(ACARS_OVERSAMPLING * (self.clock / step + 0.5)))
			window = mixed[position - ACARS_FILTER_LENGTH + 1:position + 1]
			value = np.dot(self.matched[offset], window) * cmath.exp(-1j * self.drift_phase)
			value /= abs(value) + 1e-8
			# MSK sends bits on the real and imaginary axes in turn, with the sign flipping every two bits.
			if self.symbol & 1:
				bit = value.imag
				error = -value.real if bit >= 0 else value.real
			else:
				bit = value.real
				error = value.imag if bit >= 0 else -value.imag
			self.receive_bit((-bit if self.symbol & 2 else bit) > 0)
			self.symbol = (self.symbol + 1) & 3
			self.drift = ACARS_PLL_SMOOTHING * self.drift + (1 - ACARS_PLL_SMOOTHING) * ACARS_PLL_GAIN * error

	def receive_bit(self, bit):
		# Bytes arrive least significant bit first.
		self.register = (self.register >> 1) | (0x80 if bit else 0)
		self.bits_left -= 1
		if self.bits_left <= 0:
			self.bits_left = 8
			self.receive_byte(self.register)

	def receive_byte(self, byte):
		if self.state in ("sync", "sync2"):
			if byte == ACARS_SYN ^ 0xFF:
				# The bits came out inverted, which a MSK receiver cannot tell apart on its own.
				self.symbol ^= 2
				byte = ACARS_SYN
			if byte == ACARS_SYN:
				self.state = "soh" if self.state == "sync2" else "sync2"
			elif self.state == "sync":
				self.bits_left = 1
			else:
				self.reset()
		elif self.state == "soh":
			if byte == ACARS_SOH:
				self.state = "text"
				self.block = bytearray()
			else:
				self.reset()
		elif self.state == "text":
			if not odd_parity(byte) or len(self.block) >= ACARS_MAX_LENGTH:
				self.reset()
				return
			self.block.append(byte)
			if byte in (ACARS_ETX, ACARS_ETB):
				self.state = "crc"
				self.crc = bytearray()
		elif self.state == "crc":
			self.crc.append(byte)
			if len(self.crc) == 2:
				self.finish()
				self.state = "end"
		else:
			# Skips the DEL that ends each block.
			self.reset()

	def finish(self):
		if len(self.block) < ACARS_HEADER_LENGTH or acars_crc(self.block + self.crc):
			return
		self.new.append(parse_acars(self.freq_mhz, bytes(byte & 0x7F for byte in self.block)))


class RdsDecoder:
	"""Decodes the station name and radio text from the RDS signal of one FM station."""

	def __init__(self):
		self.taps = fir_taps(PILOT_TAPS, RDS_FREQ - RDS_HALF_WIDTH, RDS_FREQ + RDS_HALF_WIDTH, MPX_RATE)
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
		rds, self.state = fir_filter(self.taps, mpx, self.state)
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
				# A station can change the text partway through sending it.
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
		self.channel_taps = fir_taps(CHANNEL_TAPS, 0, CHANNEL_CUTOFF, SDR_RATE)
		self.channel_state = np.zeros(CHANNEL_TAPS - 1, dtype=complex)
		if band.narrow_cutoff:
			self.narrow_taps = fir_taps(CHANNEL_TAPS, 0, band.narrow_cutoff, MPX_RATE)
			self.narrow_state = np.zeros(CHANNEL_TAPS - 1, dtype=complex)
		self.last_sample = 1 + 0j
		self.dc_state = (0.0, 0.0)
		n = np.arange(PILOT_TAPS) - (PILOT_TAPS - 1) // 2
		self.pilot_taps = fir_taps(PILOT_TAPS, 0, PILOT_HALF_WIDTH, MPX_RATE) * np.exp(2j * np.pi * PILOT_FREQ * n / MPX_RATE)
		self.pilot_state = np.zeros(PILOT_TAPS - 1, dtype=complex)
		self.pilot_delay = np.zeros((PILOT_TAPS - 1) // 2)
		self.audio_taps = fir_taps(AUDIO_TAPS, 0, band.audio_cutoff, MPX_RATE)
		self.audio_state = np.zeros((2, AUDIO_TAPS - 1))
		alpha = np.exp(-1 / (AUDIO_RATE * band.deemphasis_tau)) if band.deemphasis_tau else 0
		self.deemphasis_taps = (1 - alpha) * alpha ** np.arange(DEEMPHASIS_TAPS)
		self.deemphasis_state = np.zeros((2, DEEMPHASIS_TAPS - 1))
		freqs = np.fft.rfftfreq(BLOCK_SIZE // SDR_DECIMATION, 1 / MPX_RATE)
		self.pilot_bins = np.abs(freqs - PILOT_FREQ) < 2 * (freqs[1] - freqs[0])
		self.noise_bins = (freqs > PILOT_NOISE_BAND[0]) & (freqs < PILOT_NOISE_BAND[1])
		self.window = np.hanning(len(freqs) * 2 - 2)
		self.pilot_ratio = 0.0
		self.stereo = False
		self.signal_db = 0.0
		self.rds = RdsDecoder()
		self.alerts = AlertDecoder()
		self.acars = [AcarsDecoder(freq_mhz, round(freq_mhz * 1e6) - band.acars_center) for freq_mhz in band.acars_channels]

	def process(self, samples):
		if self.acars:
			for decoder in self.acars:
				decoder.process(samples)
			return np.zeros((len(samples) // (SDR_RATE // AUDIO_RATE), 2))
		spectrum = Spectrum(samples[:SCAN_SAMPLES])
		here = spectrum.channel_powers(TUNE_OFFSET, self.band)[0]
		self.signal_db += SIGNAL_SMOOTHING * (10 * np.log10(here / spectrum.floor) - self.signal_db)
		baseband = samples * self.mixer[:len(samples)]
		baseband, self.channel_state = fir_filter(self.channel_taps, baseband, self.channel_state)
		baseband = baseband[::SDR_DECIMATION]
		if self.band.narrow_cutoff:
			baseband, self.narrow_state = fir_filter(self.narrow_taps, baseband, self.narrow_state)
		if self.band.am:
			envelope = np.abs(baseband)
			mpx, self.dc_state = dc_block(envelope / envelope.mean(), self.dc_state)
		else:
			previous = np.concatenate(([self.last_sample], baseband[:-1]))
			self.last_sample = baseband[-1]
			mpx = np.angle(baseband * np.conj(previous)) * MPX_RATE / (2 * np.pi * self.band.max_deviation)
		if self.band.stereo:
			self.update_stereo(mpx)
		pilot, self.pilot_state = fir_filter(self.pilot_taps, mpx, self.pilot_state)
		delayed = np.concatenate((self.pilot_delay, mpx))
		self.pilot_delay = delayed[len(mpx):]
		delayed = delayed[:len(mpx)]
		# RDS takes its carrier and bit clock from the stereo pilot.
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
		filtered, self.audio_state = fir_filter(self.audio_taps, stacked, self.audio_state)
		mono, difference = filtered[:, ::AUDIO_DECIMATION]
		channels = np.vstack((mono + difference, mono - difference))
		channels, self.deemphasis_state = fir_filter(self.deemphasis_taps, channels, self.deemphasis_state)
		if self.band.alerts:
			self.alerts.process(channels[0])
		return channels.T

	def update_stereo(self, mpx):
		spectrum = np.abs(np.fft.rfft(mpx * self.window[:len(mpx)]))
		pilot = spectrum[self.pilot_bins].max()
		ratio = pilot / max(np.median(spectrum[self.noise_bins]), 1e-12)
		self.pilot_ratio += PILOT_SMOOTHING * (ratio - self.pilot_ratio)
		# A Hann windowed sine of amplitude A peaks at A * N / 4.
		level = 4 * pilot / len(mpx)
		self.stereo = bool(self.pilot_ratio > STEREO_THRESHOLD and level > PILOT_MIN_LEVEL)


class Resampler:
	"""Converts stereo audio from in_rate to out_rate by linear interpolation, carrying its position across blocks."""

	def __init__(self, in_rate, out_rate):
		self.in_rate = in_rate
		self.out_rate = out_rate
		self.reset()

	def reset(self):
		self.last = np.zeros((1, 2), dtype=np.float32)
		# The next output frame's position in input frames, times out_rate, so it stays exact across blocks.
		self.position = 0

	def process(self, audio):
		# Position 0 is the last frame of the previous block.
		samples = np.concatenate((self.last, audio))
		end = len(samples) - 1
		count = max(0, -(-(end * self.out_rate - self.position) // self.in_rate))
		positions = (self.position + np.arange(count) * self.in_rate) / self.out_rate
		index = positions.astype(int)
		fraction = (positions - index)[:, None]
		out = samples[index] * (1 - fraction) + samples[np.minimum(index + 1, end)] * fraction
		self.position += count * self.in_rate - end * self.out_rate
		self.last = samples[-1:]
		return out.astype(np.float32)


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


@contextlib.contextmanager
def quiet_driver():
	"""Hides what librtlsdr prints while it opens and tunes the dongle.

	The driver and nrsc5 print to the stderr of msvcrt.dll, which Python does not use. We make only that point at NUL, so other errors show as expected."""
	if sys.platform != "win32":
		yield
		return
	crt = ctypes.cdll.msvcrt
	# msvcrt.dll starts with Python's STDERR_HANDLE as its fd 2, and _dup2 closes the handle it replaces. Protected, it stays open.
	kernel32 = ctypes.windll.kernel32
	kernel32.SetHandleInformation(STDERR_HANDLE, HANDLE_FLAG_PROTECT_FROM_CLOSE, HANDLE_FLAG_PROTECT_FROM_CLOSE)
	# stderr is buffered when it is not a console - flush around the switch.
	crt.fflush(None)
	saved = crt._dup(2)
	discard = crt._open(b"NUL", os.O_WRONLY)
	crt._dup2(discard, 2)
	crt._close(discard)
	try:
		yield
	finally:
		crt.fflush(None)
		crt._dup2(saved, 2)
		crt._close(saved)
		kernel32.SetHandleInformation(STDERR_HANDLE, HANDLE_FLAG_PROTECT_FROM_CLOSE, 0)


def list_devices():
	"""Returns the connected RTL-SDR dongles."""
	count = librtlsdr.rtlsdr_get_device_count()
	serials = RtlSdr.get_device_serial_addresses() if count else []
	return [Device(i, librtlsdr.rtlsdr_get_device_name(i).decode(errors="replace"), serial) for i, serial in zip(range(count), serials)]


class HdUnavailable(Exception):
	"""libnrsc5 could not load."""


class Receiver:
	"""Plays stereo FM from an RTL-SDR dongle through the default sound card.

	Call start() to begin playing and stop() when done. on_status_change, if set, is called with no arguments from a background thread when stereo, signal_db, rds_name, rds_text, or the HD state changes."""

	def __init__(self, device_index, freq_mhz, region=None):
		region = region or detect_region()
		self.bands = REGIONS[region]
		self.acars_band = ACARS_BANDS[region]
		self.device_index = device_index
		self.open_sdr()
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
		self.county = None
		self.alert = None
		self.on_alert = None
		self.on_acars = None
		self.on_status_change = None
		self.error = None
		self.hd = None
		self.hd_resampler = Resampler(HD_AUDIO_RATE, AUDIO_RATE)
		self.reset_hd()
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

	def open_sdr(self):
		self.sdr = RtlSdr(device_index=self.device_index)
		self.sdr.sample_rate = SDR_RATE
		self.sdr.gain = SDR_GAIN

	def notify_status(self):
		if self.on_status_change:
			self.on_status_change()

	@property
	def hd_active(self):
		"""True while nrsc5 holds the dongle, from hd_start() until hd_stop(), tune(), or seek()."""
		return self.hd is not None

	def reset_hd(self):
		self.hd_locked = False
		self.hd_program = None
		self.hd_programs = {}
		self.hd_mer = None
		self.hd_resampler.reset()

	def hd_start(self):
		"""Hands the dongle to nrsc5 to play HD Radio on the current FM station. HD1 plays once its audio arrives, about 3 seconds later.

		Raises HdUnavailable if libnrsc5 cannot load, with analog still playing. Raises nrsc5.NRSC5Error if nrsc5 cannot open the dongle, with analog playing again."""
		try:
			radio = nrsc5.NRSC5(self.hd_event)
		except (OSError, nrsc5.NRSC5Error) as error:
			raise HdUnavailable(error) from error
		with self.sdr_lock:
			# Wait for the block being decoded, or its analog audio would play after the fade.
			self.raw_blocks.join()
			self.buffer.cut(FADE_FRAMES)
			self.sdr.close()
			self.sdr = None
			self.reset_hd()
			self.rds_name = self.rds_text = ""
			opened = False
			try:
				with quiet_driver():
					radio.open(self.device_index)
					opened = True
					self.hd = radio
					radio.set_auto_gain(True)
					radio.set_frequency(self.freq_mhz * 1e6)
					radio.start()
			except nrsc5.NRSC5Error:
				if self.hd:
					self.close_hd()
				elif opened:
					radio.close()
				self.tune(self.freq_mhz)
				raise
		self.notify_status()

	def hd_stop(self):
		"""Gives the dongle back to the analog receiver on the same frequency."""
		with self.sdr_lock:
			if self.hd:
				self.tune(self.freq_mhz)
		self.notify_status()

	def close_hd(self):
		"""Stops nrsc5 and frees the dongle. Call with sdr_lock held."""
		radio, self.hd = self.hd, None
		self.hd_program = None
		radio.stop()
		radio.close()
		self.reset_hd()
		self.rds_name = self.rds_text = ""

	def select_hd_program(self, program):
		"""Plays HD channel program of the current station. 0 is HD1."""
		self.hd_program = program
		self.hd_resampler.reset()
		self.rds_text = ""
		self.buffer.cut(FADE_FRAMES)
		self.notify_status()

	def hd_program_step(self, direction):
		"""Returns the HD channel found after (direction 1) or before (direction -1) the playing one, or None past either end or while no channel plays."""
		programs = sorted(self.hd_programs)
		if self.hd_program not in programs:
			return None
		index = programs.index(self.hd_program) + direction
		return programs[index] if 0 <= index < len(programs) else None

	def hd_event(self, event_type, event):
		"""Runs on the nrsc5 thread. It must not take sdr_lock, because close_hd holds it while it waits for this thread."""
		if event_type == nrsc5.EventType.AUDIO:
			self.hd_audio(event)
			return
		if event_type == nrsc5.EventType.SYNC:
			self.hd_locked = True
		elif event_type == nrsc5.EventType.LOST_SYNC:
			self.hd_locked = False
		elif event_type == nrsc5.EventType.MER:
			self.hd_mer = (event.lower, event.upper)
		elif event_type == nrsc5.EventType.STATION_NAME:
			self.rds_name = (event.name or "").strip()
		elif event_type == nrsc5.EventType.ID3:
			if event.program != self.hd_program:
				return
			self.rds_text = " - ".join(part for part in (event.artist, event.title) if part)
		elif event_type == nrsc5.EventType.SIG:
			# SIG numbers audio services from 1, and audio events number programs from 0.
			names = {service.number - 1: (service.name or "").strip() for service in event if service.type == nrsc5.ServiceType.AUDIO}
			self.hd_programs = {**self.hd_programs, **names}
		else:
			return
		self.notify_status()

	def hd_audio(self, event):
		if event.program not in self.hd_programs:
			self.hd_programs = {**self.hd_programs, event.program: ""}
			self.notify_status()
		if self.hd_program is None and event.program == 0 and self.hd:
			self.select_hd_program(0)
		if event.program == self.hd_program and not self.is_paused:
			pcm = np.frombuffer(event.data, dtype=np.int16).reshape(-1, 2)
			self.buffer.put(self.hd_resampler.process(pcm / PCM_SCALE))

	@property
	def acars_active(self):
		"""True from acars_start() until acars_stop(), tune(), or seek()."""
		return bool(self.band.acars_channels)

	def acars_start(self):
		"""Decodes ACARS on all of the region's ACARS channels at once, with no sound. on_acars, if set, is called with each AcarsMessage from a background thread."""
		self.retune(self.acars_band, self.freq_mhz, self.acars_band.acars_center)
		self.notify_status()

	def acars_stop(self):
		"""Plays the frequency tuned before acars_start() again."""
		self.tune(self.freq_mhz)
		self.notify_status()

	def start(self):
		for thread in self.threads:
			thread.start()

	def tune(self, freq_mhz):
		band = band_for(freq_mhz, self.bands)
		if band is None:
			raise ValueError(f"{freq_mhz} MHz is not in a supported band")
		freq_mhz = round(freq_mhz, 3)
		self.retune(band, freq_mhz, round(freq_mhz * 1e6) - TUNE_OFFSET)

	def retune(self, band, freq_mhz, center_freq):
		with self.sdr_lock:
			if self.hd:
				self.close_hd()
			if self.sdr is None:
				try:
					with quiet_driver():
						self.open_sdr()
				except Exception as error:
					self.error = error
					self.running = False
					return
			was_direct = bool(self.band and self.band.direct_sampling)
			try:
				with quiet_driver():
					if band.direct_sampling != was_direct:
						if was_direct:
							# Leaving direct sampling retunes to the current frequency, so it must be one the tuner can reach.
							self.sdr.center_freq = center_freq
						self.sdr.set_direct_sampling("q" if band.direct_sampling else 0)
						# Changing mode resets the tuner, including its gain.
						self.sdr.gain = SDR_GAIN
					self.sdr.center_freq = center_freq
			except LibUSBError as error:
				self.lose_dongle(error)
				return
			self.band = band
			self.freq_mhz = freq_mhz
			self.tune_count += 1

	def lose_dongle(self, error):
		"""Stops the receiver after a USB error. Call with sdr_lock held.

		The driver prints a message for each USB command the dongle drops, even when the command then works, so quiet_driver hides those and only an error that reaches Python stops the receiver."""
		self.sdr.close()
		self.sdr = None
		self.error = OSError(f"The dongle stopped responding. Try another USB port or computer. ({error})")
		self.running = False

	def guard(self, target):
		try:
			target()
		except Exception as e:
			self.error = e
			self.running = False

	def read(self):
		while self.running:
			with self.sdr_lock:
				if self.sdr is None:
					raw = None
				else:
					tune_count, band = self.tune_count, self.band
					raw = np.ctypeslib.as_array(self.sdr.read_bytes(BLOCK_SIZE * 2)).copy()
			if raw is None:
				time.sleep(HD_IDLE_SECONDS)
				continue
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
			sdr = self.sdr
			if sdr is None:
				self.raw_blocks.task_done()
				continue
			if self.demodulator is None or band is not self.demodulator.band:
				self.demodulator = Demodulator(band)
			audio = self.demodulator.process(sdr.packed_bytes_to_iq(raw)).astype(np.float32)
			if tune_count != self.played_tune_count:
				self.played_tune_count = tune_count
				self.demodulator.rds.reset()
				self.demodulator.alerts.reset()
				self.buffer.cut(FADE_FRAMES)
				audio[:len(self.fade_in)] *= self.fade_in
			new_alerts, self.demodulator.alerts.new = self.demodulator.alerts.new, []
			for alert in new_alerts:
				if alert.applies_to(self.county):
					self.alert = alert
					if self.on_alert:
						self.on_alert(alert)
			for decoder in self.demodulator.acars:
				messages, decoder.new = decoder.new, []
				for message in messages:
					if self.on_acars:
						self.on_acars(message)
			status = (self.demodulator.stereo, self.demodulator.rds.name, self.demodulator.rds.text)
			signal_db = self.demodulator.signal_db
			if status != (self.stereo, self.rds_name, self.rds_text) or abs(signal_db - self.signal_db) >= SIGNAL_HYSTERESIS_DB:
				(self.stereo, self.rds_name, self.rds_text), self.signal_db = status, round(signal_db)
				if self.on_status_change:
					self.on_status_change()
			if not self.is_paused:
				self.buffer.put(audio)
			self.raw_blocks.task_done()

	def read_audio(self, frame_count):
		"""Returns the next frame_count frames of stereo audio, before volume and mute. Use it when local_audio is off."""
		return self.buffer.get(frame_count) * OUTPUT_LEVEL

	def fill_audio(self, in_data, frame_count, time_info, status):
		audio = self.read_audio(frame_count)
		gain = 0 if self.muted or self.is_paused else self.volume_percent / MAX_VOLUME
		return (audio * gain).tobytes(), pyaudio.paContinue

	@property
	def local_audio(self):
		"""Whether the audio plays on this computer's sound card."""
		return self.stream.is_active()

	@local_audio.setter
	def local_audio(self, enabled):
		if enabled:
			self.stream.start_stream()
		else:
			self.stream.stop_stream()

	def seek(self, direction):
		"""Tunes to the next station up (direction 1) or down (direction -1) in the current band, wrapping at the band edges.

		Blocks while scanning. Returns the new frequency, or None if no other station was found."""
		band = band_for(self.freq_mhz, self.bands)
		count = round((band.max_mhz - band.min_mhz) / band.step_mhz) + 1
		start = round((self.freq_mhz - band.min_mhz) / band.step_mhz)
		channels = (round(band.min_mhz + (start + direction * i) % count * band.step_mhz, 3) for i in range(1, count))
		# Room for the measured channel and its neighbors two steps away.
		margin = 2 * band.step_mhz * 1e6 + band.half_width
		center = None
		found = None
		with self.sdr_lock:
			if self.hd:
				self.tune(self.freq_mhz)
				if self.sdr is None:
					return None
			# Fade out the current station. Wait for the block being decoded first, or it would play after the fade.
			self.raw_blocks.join()
			self.buffer.cut(FADE_FRAMES)
			try:
				for freq_mhz in channels:
					freq = round(freq_mhz * 1e6)
					if center is None or not SCAN_LOW_OFFSET + margin <= freq - center <= SCAN_HIGH_OFFSET - margin:
						# Place the capture so it covers as many of the channels ahead as it can, without a negative center frequency.
						center = max(freq - (SCAN_LOW_OFFSET + margin if direction > 0 else SCAN_HIGH_OFFSET - margin), 0)
						spectrum = self.capture(center)
					if has_station(spectrum, freq - center, band):
						found = freq_mhz
						break
			except LibUSBError as error:
				self.lose_dongle(error)
				return None
			# Tune before releasing the lock so that no block is read at the new frequency under the old tune count.
			self.tune(self.freq_mhz if found is None else found)
		return found

	def capture(self, center_freq):
		"""Tunes to center_freq and returns the spectrum around it. Call with sdr_lock held."""
		with quiet_driver():
			self.sdr.center_freq = center_freq
		self.sdr.read_bytes(SCAN_SETTLE_BYTES)
		return Spectrum(self.sdr.packed_bytes_to_iq(self.sdr.read_bytes(SCAN_SAMPLES * 2)))

	def stop(self):
		self.running = False
		for thread in self.threads:
			if thread.is_alive():
				thread.join()
		with self.sdr_lock:
			if self.hd:
				self.close_hd()
		self.stream.stop_stream()
		self.stream.close()
		self.audio.terminate()
		if self.sdr:
			self.sdr.close()


def menu(prompt, items):
	"""Constructs and shows a simple commandline menu.
	Returns an index of the provided items sequence, or None if the input is blank."""
	for i in range(len(items)):
		print(str(i + 1) + ": " + items[i])
	result = None
	while True:
		result = input(prompt)
		if not result.strip():
			return None
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


def console_width():
	"""Returns the longest line that fits the console. A longer line wraps, and \r no longer returns to its start."""
	return shutil.get_terminal_size().columns - 1


def get_title():
	title = ctypes.create_unicode_buffer(TITLE_LENGTH)
	ctypes.windll.kernel32.GetConsoleTitleW(title, TITLE_LENGTH)
	return title.value


def set_title(title):
	ctypes.windll.kernel32.SetConsoleTitleW(title)


def band_ranges(bands):
	return " or ".join(f"{band.min_mhz} to {band.max_mhz}" for band in bands)


def choose_device(devices):
	if len(devices) == 1:
		return devices[0]
	index = menu("Choose a device (blank to cancel): ", [f"{device.name} (serial {device.serial})" for device in devices])
	return None if index is None else devices[index]


class RadioCLI:
	"""Keyboard controls and a status line for a Receiver."""

	def __init__(self, receiver, alert_mode=False, sonos=None, airplay=None, log=None):
		self.receiver = receiver
		self.receiver.on_status_change = self.show_status
		self.receiver.on_alert = self.announce_alert
		self.receiver.on_acars = self.announce_acars
		self.acars_count = 0
		self.log = log
		self.alert_mode = alert_mode
		self.waiting_for_alert = alert_mode
		if alert_mode:
			receiver.muted = True
		self.sonos = sonos
		self.airplay = airplay
		self.caster = None
		self.display_lock = threading.Lock()
		self.prompting = False
		self.show_signal = False

	@property
	def output(self):
		"""Where the sound goes, with volume, muted, and paused: the Sonos group while casting, otherwise this computer."""
		return self.caster or self.receiver

	def announce_alert(self, alert):
		if self.waiting_for_alert:
			self.waiting_for_alert = False
			self.receiver.muted = False
			if self.caster:
				self.caster.paused = False
		self.show_message(alert.describe())

	def announce_acars(self, message):
		if not message.text.strip():
			return
		self.acars_count += 1
		try:
			line = flight_log.describe(message)
		except Exception:
			# ACARS text has no fixed format, so show the message as sent rather than lose it.
			line = message.describe()
		self.show_message(line)
		if self.log:
			self.log.write(f"{line}\n\t{message.describe()}\n")
			self.log.flush()

	def toggle_acars(self):
		receiver = self.receiver
		if receiver.acars_active:
			receiver.acars_stop()
			return
		self.announce_leaving_hd()
		self.acars_count = 0
		receiver.acars_start()
		channels = ", ".join(f"{freq_mhz:.3f}" for freq_mhz in receiver.band.acars_channels)
		self.show_message(f"Decoding ACARS on {channels} MHz. No sound plays.")

	def cast_targets(self, kinds):
		"""Returns (label, names, make caster) for each Sonos group and AirPlay device found, sorted so the same room sits together.

		Each kind needs its extra packages. A kind whose packages are missing finds nothing."""
		targets = []
		if "sonos" in kinds:
			try:
				from . import sonos_cast
				groups = sonos_cast.find_groups()
			except ImportError:
				groups = []
			targets += [(f"{sonos_cast.group_label(group)} (Sonos)", [member.player_name for member in group.members], partial(sonos_cast.Caster, self.receiver, group, AUDIO_RATE)) for group in groups]
		if "airplay" in kinds:
			try:
				from . import airplay_cast
				devices = airplay_cast.find_devices()
			except ImportError:
				devices = []
			targets += [(f"{device.name} (AirPlay)", [device.name], partial(airplay_cast.AirPlayCaster, self.receiver, device, AUDIO_RATE)) for device in devices]
		return sorted(targets, key=lambda target: target[0].lower())

	def start_cast(self, kinds=CAST_KINDS, name=None):
		targets = self.cast_targets(kinds)
		if name:
			targets = [target for target in targets if name.lower() in (target_name.lower() for target_name in target[1])]
		if not targets:
			self.show_message(f"error: No speaker named {name}." if name else "error: No speakers found. Sonos needs the sonos extra and AirPlay the airplay extra.")
			return
		index = 0
		if len(targets) > 1:
			index = self.prompt(lambda: menu("Cast to (blank to cancel): ", [label for label, names, make in targets]))
			if index is None:
				self.show_status()
				return
		label, names, make = targets[index]
		try:
			caster = make()
			caster.on_skip = self.seek
			caster.on_change = self.show_status
			caster.on_lost = self.cast_lost
			caster.start()
		except Exception as error:
			self.show_message(f"error: Could not cast to {label}: {error}")
			return
		self.caster = caster
		if self.waiting_for_alert:
			caster.paused = True
		self.show_message(f"Casting to {label}")

	def stop_cast(self):
		caster, self.caster = self.caster, None
		caster.stop()
		self.show_message("Stopped casting. Playing here again.")

	def cast_lost(self):
		caster, self.caster = self.caster, None
		caster.stop(release=False)
		self.show_message(f"{caster.kind}: {caster.name} stopped playing the radio. Playing here again.")

	def watch_media_keys(self):
		"""Scans when the keyboard's Previous Track or Next Track key is pressed, even when another window has focus."""
		from ctypes import wintypes
		user32 = ctypes.windll.user32
		directions = {1: -1, 2: 1}
		for hotkey, key in ((1, VK_MEDIA_PREV_TRACK), (2, VK_MEDIA_NEXT_TRACK)):
			if not user32.RegisterHotKey(None, hotkey, 0, key):
				self.show_message("Another program uses the media keys, so they will not scan.")
				return
		message = wintypes.MSG()
		while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
			if message.message == WM_HOTKEY:
				self.seek(directions[message.wParam])

	def status_text(self):
		receiver = self.receiver
		output = self.output
		frequency = receiver.band.format(receiver.freq_mhz)
		signal = f"Signal {receiver.signal_db} dB" if self.show_signal else ""
		name = receiver.rds_name
		lost = False
		if receiver.hd_active:
			program, mer = receiver.hd_program, receiver.hd_mer
			frequency += " HD" if program is None else f" HD{program + 1} of {len(receiver.hd_programs)}"
			signal = f"MER {mer[0]:.1f}/{mer[1]:.1f} dB" if self.show_signal and mer else ""
			name = receiver.hd_programs.get(program) or name
			lost = program is not None and not receiver.hd_locked
		if receiver.acars_active:
			frequency = f"ACARS {receiver.band.min_mhz:.3f} to {receiver.band.max_mhz:.3f} MHz"
			signal = f"Messages: {self.acars_count}"
		parts = [frequency, signal, name]
		if lost:
			parts.append("HD signal lost")
		if self.caster:
			parts.append(f"{self.caster.kind}: {self.caster.name}")
		if output.muted:
			parts.append("Muted")
		if output.paused:
			parts.append("Paused")
		parts.append(receiver.rds_text)
		if receiver.alert and receiver.alert.active():
			parts.insert(1, f"ALERT: {receiver.alert.name}")
		return " | ".join(part for part in parts if part)

	def show_status(self):
		with self.display_lock:
			if self.prompting:
				return
			status = self.status_text()
			width = console_width()
			sys.stdout.write("\r" + status[:width].ljust(width))
			sys.stdout.flush()
			set_title(status)

	def show_message(self, message):
		with self.display_lock:
			sys.stdout.write("\r" + " " * console_width() + "\r" + message + "\n")
		self.show_status()

	def prompt(self, ask):
		"""Runs ask, which reads from the console, without the status line drawing over it."""
		with self.display_lock:
			self.prompting = True
			sys.stdout.write("\n")
		try:
			return ask()
		finally:
			self.prompting = False

	def prompt_frequency(self):
		text = self.prompt(lambda: input(f"Frequency in MHz ({band_ranges(self.receiver.bands)}): "))
		try:
			freq_mhz = float(text)
		except ValueError:
			self.show_message("error: Input must be a number.")
			return
		if band_for(freq_mhz, self.receiver.bands) is None:
			self.show_message("error: Frequency not in range.")
			return
		self.announce_leaving_hd()
		self.receiver.tune(freq_mhz)
		self.show_status()

	def seek(self, direction):
		self.announce_leaving_hd()
		with self.display_lock:
			sys.stdout.write("\r" + "Scanning...".ljust(60))
			sys.stdout.flush()
		if self.receiver.seek(direction) is None and self.receiver.running:
			self.show_message("No other station found.")

	def step(self, direction):
		band = band_for(self.receiver.freq_mhz, self.receiver.bands)
		freq_mhz = self.receiver.freq_mhz + direction * band.step_mhz
		if band_for(freq_mhz, self.receiver.bands) is band:
			self.announce_leaving_hd()
			self.receiver.tune(freq_mhz)

	def announce_leaving_hd(self):
		if self.receiver.hd_active:
			self.show_message("Switching back to analog...")

	def step_hd(self, direction):
		"""Moves through analog, HD1, HD2, and so on: forward for direction 1, back for -1."""
		receiver = self.receiver
		if not receiver.band.hd:
			self.show_message("HD works only on FM.")
			return
		if not receiver.hd_active:
			self.start_hd()
			return
		program = receiver.hd_program_step(direction)
		if program is None:
			self.show_message("Switching back to analog...")
			receiver.hd_stop()
			return
		receiver.select_hd_program(program)
		self.show_message(f"HD{program + 1} {receiver.hd_programs.get(program, '')}".strip())

	def start_hd(self):
		self.show_message("Checking for HD...")
		try:
			self.receiver.hd_start()
		except HdUnavailable as error:
			self.show_message(f"HD not available: {error}")
			return
		except nrsc5.NRSC5Error as error:
			self.show_message(f"error: Could not start HD: {error}")
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
				self.show_message("HD found, retrieving channels...")
				return
			time.sleep(KEY_POLL_SECONDS)
		if receiver.hd is radio:
			receiver.hd_stop()
			self.show_message(f"No HD on {receiver.band.format(receiver.freq_mhz)}.")

	def handle_key(self, key):
		output = self.output
		if key == " ":
			output.paused = not output.paused
		elif key == "_":
			output.volume -= VOLUME_STEP
		elif key == "+":
			output.volume += VOLUME_STEP
		elif key == "s":
			self.step(-1)
		elif key == "w":
			self.step(1)
		elif key == "S":
			self.seek(-1)
		elif key == "W":
			self.seek(1)
		elif key == "d":
			self.step_hd(1)
			return
		elif key == "D":
			self.step_hd(-1)
			return
		elif key == "m":
			output.muted = not output.muted
		elif key == "a":
			self.toggle_acars()
			return
		elif key == "c":
			if self.caster:
				self.stop_cast()
			else:
				self.start_cast()
			return
		elif key == "i":
			self.show_signal = not self.show_signal
		elif key == "h":
			self.show_message(HELP_TEXT)
			return
		elif key == "t":
			self.prompt_frequency()
			return
		self.show_status()

	def run(self):
		original_title = get_title()
		print(HELP_TEXT)
		if self.alert_mode:
			print("Alert mode: the sound stays off until a weather alert arrives.")
		self.show_status()
		self.receiver.start()
		threading.Thread(target=self.watch_media_keys, daemon=True).start()
		if self.sonos is not None:
			self.start_cast(("sonos",), self.sonos)
		if self.airplay is not None:
			self.start_cast(("airplay",), self.airplay)
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
			if self.caster:
				self.caster.stop()
			self.receiver.stop()
			set_title(original_title)
			print()


def main():
	parser = argparse.ArgumentParser(description="Listen to AM, FM, or NOAA weather radio with an RTL-SDR dongle.")
	parser.add_argument("-v", "--version", action="version", version=VERSION_TEXT)
	parser.add_argument("frequency", type=float, nargs="?", default=FM.min_mhz, help=f"Frequency in MHz. Default is {FM.min_mhz}.")
	parser.add_argument("--region", choices=REGIONS, help="Band plan to use. Default is from the system's country setting.")
	parser.add_argument("--county", help="Only report weather alerts for this 5 or 6 digit county FIPS code.")
	parser.add_argument("--alert-mode", action="store_true", help="Keep the sound off until a weather alert arrives. Needs a NOAA frequency.")
	parser.add_argument("--acars", action="store_true", help="Start by decoding ACARS messages from aircraft. The a key goes back to the frequency.")
	parser.add_argument("--log", metavar="FILE", help="Add each ACARS message to this file, as a readable line and as sent.")
	cast = parser.add_mutually_exclusive_group()
	cast.add_argument("--sonos", nargs="?", const="", metavar="SPEAKER", help="Cast to the Sonos group with this speaker in it. Without a name, choose from a list.")
	cast.add_argument("--airplay", nargs="?", const="", metavar="DEVICE", help="Cast to this AirPlay device. Without a name, choose from a list.")
	args = parser.parse_args()
	print(VERSION_TEXT)
	# Library log messages would print over the status line. Without a handler, the first one also turns on console logging for all of them.
	logging.getLogger().addHandler(logging.NullHandler())
	region = args.region or detect_region()
	band = band_for(args.frequency, REGIONS[region])
	if band is None:
		parser.error(f"frequency must be from {band_ranges(REGIONS[region])} MHz")
	if args.county and not re.fullmatch(r"\d{5,6}", args.county):
		parser.error("county must be a 5 or 6 digit FIPS code")
	if args.alert_mode and not band.alerts:
		parser.error("--alert-mode needs a NOAA weather radio frequency")
	if args.alert_mode and args.acars:
		parser.error("--alert-mode cannot be used with --acars")
	devices = list_devices()
	if not devices:
		print("error: No RTL-SDR devices found.")
		return 1
	device = choose_device(devices)
	if device is None:
		return 0
	try:
		log = open(args.log, "a", encoding="utf-8") if args.log else None
	except OSError as error:
		print(f"error: Could not open the log file: {error}")
		return 1
	receiver = Receiver(device.index, args.frequency, region)
	receiver.county = args.county
	if args.acars:
		receiver.acars_start()
	with log or contextlib.nullcontext():
		RadioCLI(receiver, args.alert_mode, args.sonos, args.airplay, log).run()
	if receiver.error:
		print(f"error: {receiver.error}")
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
