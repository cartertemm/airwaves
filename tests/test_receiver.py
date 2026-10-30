import threading

from airwaves import sdr

WAIT_TIMEOUT_SECONDS = 5


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


class BrokenDemodulator:
	def __init__(self, band):
		self.band = band

	def process(self, iq):
		raise ValueError("bad block")


def test_a_demodulate_error_does_not_hang_the_wait_for_queued_blocks(monkeypatch):
	monkeypatch.setattr(sdr.pyaudio, "PyAudio", NoSoundCard)
	monkeypatch.setattr(sdr, "RtlSdr", FakeRtlSdr)
	monkeypatch.setattr(sdr, "Demodulator", BrokenDemodulator)
	receiver = sdr.Receiver(0, 97.9, "us")
	receiver.sdr.packed_bytes_to_iq = lambda raw: raw
	for _ in range(2):
		receiver.raw_blocks.put((receiver.tune_count, receiver.band, None))
	threading.Thread(target=receiver.guard, args=(receiver.demodulate,), daemon=True).start()
	waiter = threading.Thread(target=receiver.wait_for_demodulate, daemon=True)
	waiter.start()
	waiter.join(WAIT_TIMEOUT_SECONDS)
	assert not waiter.is_alive()
	assert isinstance(receiver.error, ValueError)
	receiver.stop()
