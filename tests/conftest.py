import numpy as np
import pytest

from airwaves import sdr


class FakeReceiver:
	"""Stands in for sdr.Receiver with no dongle and no sound card. seek() records the direction and returns seek_result."""

	hd_active = sdr.Receiver.hd_active
	acars_active = sdr.Receiver.acars_active
	hd_program_step = sdr.Receiver.hd_program_step

	def __init__(self, freq_mhz=97.9):
		self.bands = sdr.REGIONS["us"]
		self.band = sdr.band_for(freq_mhz, self.bands)
		self.freq_mhz = freq_mhz
		self.has_sound_card = True
		self.local_audio = True
		self.volume = 50
		self.muted = False
		self.paused = False
		self.running = True
		self.rds_name = "KXYZ"
		self.rds_text = ""
		self.signal_db = 20
		self.alert = None
		self.hd = None
		self.hd_locked = True
		self.hd_program = None
		self.hd_programs = {}
		self.hd_mer = None
		self.seeks = []
		self.seek_result = None
		self.on_status_change = self.on_alert = self.on_acars = None

	def tune(self, freq_mhz):
		self.band = sdr.band_for(freq_mhz, self.bands)
		self.freq_mhz = round(freq_mhz, 3)

	def seek(self, direction):
		self.seeks.append(direction)
		return self.seek_result

	def hd_start(self):
		self.hd = object()
		self.hd_programs = {0: "One", 1: "Two"}

	def hd_stop(self):
		self.hd = None
		self.hd_program = None

	def select_hd_program(self, program):
		self.hd_program = program

	def read_audio(self, frame_count):
		return np.zeros((frame_count, 2), dtype=np.float32)


class FakeCaster:
	kind = "Sonos"
	name = "Kitchen"

	def __init__(self, receiver):
		self.receiver = receiver
		self.volume = 30
		self.muted = False
		self.paused = False
		self.started = False
		self.released = None

	def start(self):
		self.started = True
		self.receiver.local_audio = False

	def stop(self, release=True):
		self.released = release
		self.receiver.local_audio = True


@pytest.fixture
def receiver():
	return FakeReceiver()


@pytest.fixture(autouse=True)
def in_tmp_folder(tmp_path, monkeypatch):
	"""config reads and writes airwaves.conf in the current folder. The repo's copy holds real presets."""
	monkeypatch.chdir(tmp_path)
