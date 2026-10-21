from airwaves import sdr


class NoSoundCard:
	"""Stands in for pyaudio.PyAudio on a computer with no output device."""

	def open(self, **kwargs):
		raise OSError("No Default Output Device Available")

	def terminate(self):
		pass


class FakeRtlSdr:
	def __init__(self, device_index):
		self.gain = None
		self.freq_correction = 0

	def set_direct_sampling(self, mode):
		# Like the driver, changing mode resets the tuner's gain.
		self.gain = None

	def close(self):
		pass


def test_bands_have_names():
	assert [band.name for band in sdr.REGIONS["us"]] == ["AM", "Shortwave", "FM", "Aviation", "Weather"]
	assert [band.name for band in sdr.REGIONS["eu"]] == ["AM", "Shortwave", "FM", "Aviation"]
	assert sdr.ACARS.name == "Aviation"


def test_receiver_runs_without_a_sound_card(monkeypatch):
	monkeypatch.setattr(sdr.pyaudio, "PyAudio", NoSoundCard)
	monkeypatch.setattr(sdr, "RtlSdr", FakeRtlSdr)
	receiver = sdr.Receiver(0, 97.9, "us")
	assert not receiver.has_sound_card
	assert not receiver.local_audio
	receiver.local_audio = True
	assert not receiver.local_audio
	receiver.stop()


def test_receiver_keeps_its_gain_when_the_sampling_mode_changes(monkeypatch):
	monkeypatch.setattr(sdr.pyaudio, "PyAudio", NoSoundCard)
	monkeypatch.setattr(sdr, "RtlSdr", FakeRtlSdr)
	receiver = sdr.Receiver(0, 97.9, "us", 30.0)
	assert receiver.sdr.gain == 30.0
	receiver.tune(1.4)
	assert receiver.sdr.gain == 30.0
	receiver.tune(97.9)
	assert receiver.sdr.gain == 30.0
	receiver.stop()


def test_receiver_gain_is_auto_by_default(monkeypatch):
	monkeypatch.setattr(sdr.pyaudio, "PyAudio", NoSoundCard)
	monkeypatch.setattr(sdr, "RtlSdr", FakeRtlSdr)
	receiver = sdr.Receiver(0, 97.9, "us")
	assert receiver.sdr.gain == sdr.AUTO_GAIN
	receiver.stop()


def test_receiver_sets_the_ppm_correction(monkeypatch):
	monkeypatch.setattr(sdr.pyaudio, "PyAudio", NoSoundCard)
	monkeypatch.setattr(sdr, "RtlSdr", FakeRtlSdr)
	receiver = sdr.Receiver(0, 97.9, "us", ppm=-42)
	assert receiver.sdr.freq_correction == -42
	receiver.stop()
