import queue
import threading
import time

import pytest

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


class OfflineCoordinator:
	def get_current_track_info(self):
		raise OSError("no route to host")


def offline_caster(monkeypatch, clock):
	pytest.importorskip("soco")
	monkeypatch.setattr(sonos_cast.time, "monotonic", lambda: clock[0])
	caster = sonos_cast.Caster.__new__(sonos_cast.Caster)
	caster.coordinator = OfflineCoordinator()
	caster.running = True
	caster.failing_since = None
	caster.lost = 0

	def on_lost():
		caster.lost += 1

	caster.on_lost = on_lost
	return caster


def test_sonos_that_stops_answering_is_lost_after_a_while(monkeypatch):
	clock = [100.0]
	caster = offline_caster(monkeypatch, clock)
	caster.check()
	clock[0] += sonos_cast.LOST_SECONDS - 1
	caster.check()
	assert caster.lost == 0 and caster.running
	clock[0] += 1
	caster.check()
	caster.check()
	assert caster.lost == 1 and not caster.running


def test_sonos_answering_again_resets_the_lost_timer(monkeypatch):
	clock = [100.0]
	caster = offline_caster(monkeypatch, clock)
	caster.check()
	clock[0] += sonos_cast.LOST_SECONDS - 1
	caster.stream = type("Stream", (), {"address": "http://10.0.0.2:8000/"})()
	caster.coordinator = type("Answering", (), {
		"get_current_track_info": lambda self: {"uri": "", "playlist_position": "1"},
		"get_current_transport_info": lambda self: {"current_transport_state": "PLAYING"},
		"group": type("Group", (), {"mute": False, "volume": 20})(),
	})()
	caster.position = None
	caster.check()
	caster.coordinator = OfflineCoordinator()
	clock[0] += 1
	caster.check()
	assert caster.lost == 0 and caster.running


def test_sonos_check_does_not_hide_programming_errors(monkeypatch):
	caster = offline_caster(monkeypatch, [0.0])
	caster.coordinator = type("Broken", (), {"get_current_track_info": lambda self: None["uri"]})()
	try:
		caster.check()
	except TypeError:
		return
	raise AssertionError("check() hid a TypeError")
