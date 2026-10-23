import asyncio
import base64
import re
import socket
import threading

import pytest

pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer

from airwaves import config, web
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
	("save_preset", {"number": 2}, lambda receiver: config.presets().get(2) == "97.9"),
	("delete_preset", {"number": 5}, lambda receiver: True),
	("hd_step", {"direction": 1}, lambda receiver: receiver.hd is not None),
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
	("save_preset", {"number": 0}),
	("delete_preset", {}),
	("hd_step", {"direction": 0}),
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
		assert [band["name"] for band in state["bands"] if band["hd"]] == ["FM"]
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


def test_static_files_are_served_with_their_types(receiver, tmp_path, monkeypatch):
	(tmp_path / "views").mkdir()
	for name in ("index.html", "app.css", "views/panel.js", "icon.svg", "manifest.webmanifest", "notes.txt"):
		(tmp_path / name).write_text("x", encoding="utf-8")
	monkeypatch.setattr(web, "STATIC_FOLDER", str(tmp_path))

	async def check(client, radio):
		for path, content_type in (
			("/", "text/html"),
			("/app.css", "text/css"),
			("/views/panel.js", "text/javascript"),
			("/icon.svg", "image/svg+xml"),
			("/manifest.webmanifest", "application/manifest+json"),
		):
			response = await client.get(path)
			assert response.status == 200, path
			assert response.content_type == content_type
		for path in ("/notes.txt", "/missing.js", "/views"):
			assert (await client.get(path)).status == 404, path
		assert (await client.get("/api/state")).content_type == "application/json"
	serve(receiver, check)


def test_static_file_refuses_paths_outside_the_folder(tmp_path, monkeypatch):
	folder = tmp_path / "static"
	folder.mkdir()
	(folder / "index.html").write_text("x", encoding="utf-8")
	(tmp_path / "outside.js").write_text("x", encoding="utf-8")
	monkeypatch.setattr(web, "STATIC_FOLDER", str(folder))
	assert web.static_file("../web.py") is None
	assert web.static_file("../outside.js") is None
	assert web.static_file(str(tmp_path / "outside.js")) is None
	assert web.static_file("index.html") is not None


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


def test_run_starts_paused_on_the_sound_card(receiver):
	paused = []
	receiver.start = lambda: paused.append(receiver.paused)
	receiver.stop = lambda: None
	with socket.socket() as probe:
		probe.bind((web.HOST, 0))
		port = probe.getsockname()[1]
	threading.Timer(0.3, lambda: setattr(receiver, "running", False)).start()
	assert web.run(Radio(receiver), port) is True
	assert paused == [True]


def test_presets_are_read_again_only_after_preset_commands(receiver):
	async def presets(client):
		state = await (await client.get("/api/state")).json()
		return [preset["label"] for preset in state["presets"]]

	async def check(client, radio):
		config.save("1", "101.1", config.PRESETS)
		assert await presets(client) == []
		response = await client.post("/api/save_preset", json={})
		assert response.status == 202
		for _ in range(round(WAIT_SECONDS / WAIT_STEP_SECONDS)):
			if await presets(client) == ["101.1 MHz", "97.9 MHz"]:
				return
			await asyncio.sleep(WAIT_STEP_SECONDS)
		raise AssertionError("The presets were not read again.")
	serve(receiver, check)
