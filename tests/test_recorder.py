import wave

import numpy as np

from airwaves.recorder import Recorder

RATE = 48000


def block(frames, level=0.5):
	return np.full((frames, 2), level, dtype=np.float32)


def test_wav_holds_the_audio(tmp_path):
	path = str(tmp_path / "a.wav")
	recorder = Recorder(path, RATE, mp3=False)
	recorder.write(block(4800))
	recorder.write(block(4800))
	recorder.close()
	with wave.open(path) as file:
		assert (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getnframes()) == (2, 2, RATE, 9600)
		samples = np.frombuffer(file.readframes(9600), dtype=np.int16)
	assert samples.min() == samples.max() == 16383


def test_wav_clips_loud_audio(tmp_path):
	path = str(tmp_path / "a.wav")
	recorder = Recorder(path, RATE, mp3=False)
	recorder.write(block(100, level=3.0))
	recorder.close()
	with wave.open(path) as file:
		samples = np.frombuffer(file.readframes(100), dtype=np.int16)
	assert samples.max() == 32767


def test_mp3_is_about_320_kbps(tmp_path):
	path = tmp_path / "a.mp3"
	recorder = Recorder(str(path), RATE, mp3=True)
	for _ in range(10):
		recorder.write(block(4800))
	recorder.close()
	data = path.read_bytes()
	assert data[0] == 0xFF and data[1] & 0xE0 == 0xE0
	assert 30000 < len(data) < 50000


def test_write_error_stops_and_reports(tmp_path):
	class Broken:
		def write(self, data):
			raise OSError("disk full")

		def close(self):
			pass

	path = str(tmp_path / "a.mp3")
	recorder = Recorder(path, RATE, mp3=True)
	recorder.file.close()
	recorder.file = Broken()
	errors = []
	recorder.on_error = errors.append
	recorder.write(block(100))
	recorder.close()
	assert [str(error) for error in errors] == ["disk full"]
	assert recorder.running is False


def test_bad_folder_raises_on_open(tmp_path):
	path = str(tmp_path / "missing" / "a.wav")
	try:
		Recorder(path, RATE, mp3=False)
	except OSError:
		return
	assert False, "expected OSError"
