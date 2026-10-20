from airwaves import sdr


class NoSoundCard:
	"""Stands in for pyaudio.PyAudio on a computer with no output device."""

	def open(self, **kwargs):
		raise OSError("No Default Output Device Available")

	def terminate(self):
		pass


class FakeRtlSdr:
	def __init__(self, device_index):
		pass

	def set_direct_sampling(self, mode):
		pass

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
