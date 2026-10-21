import queue
import threading
import time

from airwaves import sonos_cast
from airwaves.sonos_cast import StreamServer

RATE = 48000


def test_stream_without_http_sends_mp3_to_clients(receiver):
	stream = StreamServer(receiver, RATE, None, serve_http=False)
	stream.start()
	client = queue.Queue()
	stream.add_client(client)
	try:
		data = b""
		while not data:
			data = client.get(timeout=2)
	finally:
		stream.stop()
	assert data[0] == 0xFF and data[1] & 0xE0 == 0xE0
	assert not hasattr(stream, "server")


def test_stream_without_clients_reads_audio_but_does_not_encode(receiver, monkeypatch):
	encoded = []
	read = threading.Event()

	class Encoder:
		def encode(self, pcm):
			encoded.append(pcm)
			return b""

	def read_audio(frame_count):
		read.set()
		return receiver.read_audio(frame_count)

	monkeypatch.setattr(sonos_cast, "silent_chunk", lambda rate: b"")
	monkeypatch.setattr(sonos_cast, "new_encoder", lambda rate: Encoder())
	stream = StreamServer(receiver, RATE, None, serve_http=False, read_audio=read_audio)
	stream.start()
	try:
		assert read.wait(2)
		time.sleep(3 * sonos_cast.CHUNK_SECONDS)
	finally:
		stream.stop()
	assert not encoded
