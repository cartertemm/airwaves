import asyncio
import base64
import re
import socket
import threading

import pytest

pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer

from airwaves import web
from airwaves.radio import BROWSERS, Radio

WAIT_STEP_SECONDS = 0.01
WAIT_SECONDS = 2
MP3_SAMPLE_BYTES = 1000


def serve(receiver, check, password=None):
	"""Runs the coroutine check(client, radio) against a web server for a Radio on receiver."""
	async def main():
		radio = Radio(receiver)
		server = web.WebServer(radio, password)
		async with TestClient(TestServer(server.make_app())) as client:
			try:
				await check(client, radio)
			finally:
				radio.close()
	asyncio.run(main())


async def until(condition):
	"""Commands run on a worker thread. Waits for one to take effect."""
	for _ in range(round(WAIT_SECONDS / WAIT_STEP_SECONDS)):
		if condition():
			return
		await asyncio.sleep(WAIT_STEP_SECONDS)
	raise AssertionError("The command did not run.")


@pytest.mark.parametrize("command, body, done", [
	("tune", {"mhz": 99.5}, lambda receiver: receiver.freq_mhz == 99.5),
	("step", {"direction": 1}, lambda receiver: receiver.freq_mhz == 98.0),
	("seek", {"direction": -1}, lambda receiver: receiver.seeks == [-1]),
	("band", {"name": "AM"}, lambda receiver: receiver.freq_mhz == 0.53),
	("hd", {"program": 1}, lambda receiver: receiver.hd_program == 1),
	("volume", {"percent": 70}, lambda receiver: receiver.volume == 70),
	("mute", {"muted": True}, lambda receiver: receiver.muted),
	("pause", {"paused": True}, lambda receiver: receiver.paused),
])
def test_commands_reach_the_receiver(receiver, command, body, done):
	async def check(client, radio):
		response = await client.post(f"/api/{command}", json=body)
		assert response.status == 202
		await until(lambda: done(receiver))
	serve(receiver, check)


def test_output_command_starts_the_browser_stream(receiver):
	async def check(client, radio):
		response = await client.post("/api/output", json={"target": BROWSERS})
		assert response.status == 202
		await until(lambda: radio.browser_stream is not None)
	serve(receiver, check)


@pytest.mark.parametrize("command, body", [
	("tune", {"mhz": "fast"}),
	("step", {"direction": 2}),
	("step", {"direction": True}),
	("hd", {}),
	("mute", {"muted": 1}),
	("preset", {"number": 1.5}),
	("output", {"target": "Kitchen (Sonos)"}),
])
def test_bad_bodies_are_refused(receiver, command, body):
	async def check(client, radio):
		response = await client.post(f"/api/{command}", json=body)
		assert response.status == 400
		assert "error" in await response.json()
	serve(receiver, check)


def test_unknown_command_is_not_found(receiver):
	async def check(client, radio):
		response = await client.post("/api/explode", json={})
		assert response.status == 404
	serve(receiver, check)


def test_commands_must_be_json(receiver):
	async def check(client, radio):
		response = await client.post("/api/tune", data='{"mhz": 99.5}', headers={"Content-Type": "text/plain"})
		assert response.status == 415
	serve(receiver, check)


def test_password_is_checked(receiver):
	def basic(credentials):
		return {"Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()}

	async def check(client, radio):
		assert (await client.get("/api/state")).status == 401
		assert (await client.get("/api/state", headers=basic("any:wrong"))).status == 401
		assert (await client.get("/stream", headers=basic("any:wrong"))).status == 401
		assert (await client.get("/api/state", headers=basic("any:secret"))).status == 200
	serve(receiver, check, password="secret")


def test_state_lists_bands_and_outputs(receiver):
	async def check(client, radio):
		state = await (await client.get("/api/state")).json()
		assert [band["name"] for band in state["bands"]] == ["AM", "Shortwave", "FM", "Aviation", "Weather"]
		assert state["outputs"] == ["local", "browsers"]
		assert state["frequency"] == "97.9 MHz"
		assert state["presets"] == []
	serve(receiver, check)


def test_state_without_a_sound_card_has_no_local_output(receiver):
	receiver.has_sound_card = False

	async def check(client, radio):
		state = await (await client.get("/api/state")).json()
		assert state["outputs"] == ["browsers"]
	serve(receiver, check)


def test_events_start_with_the_status(receiver):
	async def check(client, radio):
		response = await client.get("/events")
		assert response.headers["Content-Type"] == "text/event-stream"
		first = await response.content.readuntil(b"\n\n")
		assert first.startswith(b"event: status\ndata: {")
		radio.message("Hello")
		second = await response.content.readuntil(b"\n\n")
		assert second == b'event: message\ndata: {"text": "Hello", "error": false}\n\n'
		response.close()
	serve(receiver, check)


def test_stream_needs_the_browsers_output(receiver):
	async def check(client, radio):
		response = await client.get("/stream")
		assert response.status == 409
	serve(receiver, check)


def test_stream_sends_mp3(receiver):
	async def check(client, radio):
		radio.set_output(BROWSERS)
		response = await client.get("/stream")
		assert response.headers["Content-Type"] == "audio/mpeg"
		data = await response.content.readexactly(MP3_SAMPLE_BYTES)
		assert re.search(rb"\xff[\xe0-\xff]", data)
		response.close()
	serve(receiver, check)


def test_page_files_are_served(receiver):
	async def check(client, radio):
		for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript"), ("/app.css", "text/css")):
			response = await client.get(path)
			assert response.status == 200
			assert response.content_type == content_type
	serve(receiver, check)


@pytest.mark.parametrize("value", ["Infinity", "NaN"])
def test_numbers_must_be_finite(receiver, value):
	async def check(client, radio):
		response = await client.post("/api/volume", data=f'{{"percent": {value}}}', headers={"Content-Type": "application/json"})
		assert response.status == 400
	serve(receiver, check)


def test_run_does_not_start_when_the_port_is_taken(receiver, capsys):
	calls = []
	receiver.start = lambda: calls.append("start")
	receiver.stop = lambda: calls.append("stop")
	with socket.socket() as taken:
		taken.bind((web.HOST, 0))
		taken.listen()
		assert web.run(Radio(receiver), taken.getsockname()[1]) is False
	assert calls == ["stop"]
	assert "Could not start the web server" in capsys.readouterr().out


def test_run_starts_after_binding_and_stops_when_the_receiver_stops(receiver):
	calls = []
	receiver.start = lambda: calls.append("start")
	receiver.stop = lambda: calls.append("stop")
	receiver.has_sound_card = False
	radio = Radio(receiver)
	with socket.socket() as probe:
		probe.bind((web.HOST, 0))
		port = probe.getsockname()[1]
	threading.Timer(0.3, lambda: setattr(receiver, "running", False)).start()
	assert web.run(radio, port) is True
	assert calls == ["start", "stop"]
	assert radio.browser_stream is None
