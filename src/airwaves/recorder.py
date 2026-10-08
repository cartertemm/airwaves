import queue
import threading
import wave

import lameenc
import numpy as np

BITRATE = 320
MP3_QUALITY = 2
PCM_SCALE = 32767
QUEUE_TIMEOUT_SECONDS = 0.5


def new_encoder(audio_rate):
	encoder = lameenc.Encoder()
	encoder.set_bit_rate(BITRATE)
	encoder.set_in_sample_rate(audio_rate)
	encoder.set_channels(2)
	encoder.set_quality(MP3_QUALITY)
	return encoder


def to_pcm(audio):
	"""Turns stereo audio from -1 to 1 into 16-bit little-endian bytes."""
	return (np.clip(audio, -1, 1) * PCM_SCALE).astype(np.int16).tobytes()


class Recorder:
	"""Writes stereo audio to a WAV or MP3 file on its own thread.

	Call write(audio) from any thread with arrays of shape (frames, 2) from -1 to 1, and close() when done. Opening raises OSError if the file cannot be created. on_error, if set, is called on the recorder thread with the OSError that stopped the recording."""

	def __init__(self, path, audio_rate, mp3):
		self.path = path
		self.on_error = None
		self.blocks = queue.Queue()
		self.running = True
		if mp3:
			self.encoder = new_encoder(audio_rate)
			self.file = open(path, "wb")
		else:
			self.encoder = None
			self.file = wave.open(path, "wb")
			self.file.setnchannels(2)
			self.file.setsampwidth(2)
			self.file.setframerate(audio_rate)
		self.thread = threading.Thread(target=self.run, daemon=True)
		self.thread.start()

	def write(self, audio):
		if self.running:
			self.blocks.put(audio)

	def close(self):
		"""Writes the queued audio, finishes the file, and returns."""
		self.running = False
		self.thread.join()

	def run(self):
		try:
			while self.running or not self.blocks.empty():
				try:
					audio = self.blocks.get(timeout=QUEUE_TIMEOUT_SECONDS)
				except queue.Empty:
					continue
				self.write_pcm(to_pcm(audio))
			if self.encoder:
				self.file.write(bytes(self.encoder.flush()))
		except OSError as error:
			self.running = False
			if self.on_error:
				self.on_error(error)
		finally:
			self.file.close()

	def write_pcm(self, pcm):
		if self.encoder:
			self.file.write(bytes(self.encoder.encode(pcm)))
		else:
			# writeframes patches the header on every call. The header is written once, on close.
			self.file.writeframesraw(pcm)
