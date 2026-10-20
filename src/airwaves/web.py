"""The web frontend: a page that controls the radio from any browser on the network."""

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import hmac
import json
import math
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from aiohttp import web as aioweb

from .radio import BROWSERS, LOCAL
from .sdr import CAST_KINDS
from .sonos_cast import CLIENT_BACKLOG

HOST = "0.0.0.0"
# A comment this often keeps phones and proxies from closing a quiet event stream.
KEEPALIVE_SECONDS = 15
EVENT_BACKLOG = 100
STREAM_WAIT_SECONDS = 1
RUNNING_CHECK_SECONDS = 0.5
STATIC_FOLDER = os.path.join(os.path.dirname(__file__), "static")
# Windows can map .js to text/plain, so the types are set here. Other file types are not served.
STATIC_TYPES = {
	".html": "text/html",
	".js": "text/javascript",
	".css": "text/css",
	".svg": "image/svg+xml",
	".webmanifest": "application/manifest+json",
}
# Connecting a UDP socket sends nothing. It only picks the network interface that reaches this address.
PROBE_ADDRESS = ("8.8.8.8", 80)


def lan_address():
	"""Returns this computer's address on the local network, or 127.0.0.1 without a network."""
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
			probe.connect(PROBE_ADDRESS)
			return probe.getsockname()[0]
	except OSError:
		return "127.0.0.1"


def event_bytes(name, data):
	return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def number(body, key):
	value = body.get(key)
	if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
		raise ValueError(f"{key} must be a number.")
	return value


def whole_number(body, key):
	value = body.get(key)
	if isinstance(value, bool) or not isinstance(value, int):
		raise ValueError(f"{key} must be a whole number.")
	return value


def direction(body):
	value = body.get("direction")
	if isinstance(value, bool) or value not in (1, -1):
		raise ValueError("direction must be 1 or -1.")
	return value


def flag(body, key):
	value = body.get(key)
	if not isinstance(value, bool):
		raise ValueError(f"{key} must be true or false.")
	return value


def text(body, key):
	value = body.get(key)
	if not isinstance(value, str):
		raise ValueError(f"{key} must be text.")
	return value


def hd_program(body):
	"""Returns the HD program (0 is HD1), or None for analog."""
	if "program" not in body:
		raise ValueError("program must be a whole number from 0, or null for analog.")
	if body["program"] is None:
		return None
	value = whole_number(body, "program")
	if value < 0:
		raise ValueError("program must be a whole number from 0, or null for analog.")
	return value


def preset_number(body, required=True):
	"""Returns the preset number (1 or more), or None when it may be left out and is."""
	if not required and body.get("number") is None:
		return None
	value = whole_number(body, "number")
	if value < 1:
		raise ValueError("number must be 1 or more.")
	return value


def static_file(path):
	"""Returns (file path, content type) for a page file under STATIC_FOLDER, or None if it is missing, outside the folder, or of a type the page does not use."""
	folder = os.path.realpath(STATIC_FOLDER)
	full = os.path.realpath(os.path.join(folder, path))
	try:
		inside = os.path.commonpath([full, folder]) == folder
	except ValueError:
		inside = False
	content_type = STATIC_TYPES.get(os.path.splitext(full)[1])
	if not inside or content_type is None or not os.path.isfile(full):
		return None
	return full, content_type


class LoopQueue:
	"""A StreamServer client that passes audio to an asyncio queue. put_nowait runs on the encode thread."""

	def __init__(self, loop):
		self.loop = loop
		self.queue = asyncio.Queue(maxsize=CLIENT_BACKLOG)

	def put_nowait(self, data):
		with contextlib.suppress(RuntimeError):
			self.loop.call_soon_threadsafe(self.offer, data)

	def offer(self, data):
		# A connection too slow for the stream loses audio instead of holding it all.
		with contextlib.suppress(asyncio.QueueFull):
			self.queue.put_nowait(data)


class WebServer:
	"""Serves the page, its events and commands, and the browser audio stream for one Radio.

	Commands run one at a time on a worker thread, like keys in the terminal, because seek and finding speakers block."""

	def __init__(self, radio, password=None):
		self.radio = radio
		self.password = password
		self.worker = ThreadPoolExecutor(max_workers=1)
		self.listeners = set()
		self.speakers = []
		# Read once here and after preset commands. Reading airwaves.conf for each status event could catch a save half written.
		self.presets = radio.presets()
		self.loop = None
		self.status_pending = False
		self.stopping = False
		self.commands = {
			"tune": lambda body: partial(radio.tune, number(body, "mhz")),
			"step": lambda body: partial(radio.step, direction(body)),
			"seek": lambda body: partial(radio.seek, direction(body)),
			"band": lambda body: partial(radio.tune_band, text(body, "name")),
			"hd": lambda body: partial(radio.select_hd, hd_program(body)),
			"preset": lambda body: partial(self.update_presets, partial(radio.choose_preset, whole_number(body, "number"))),
			"save_preset": lambda body: partial(self.update_presets, partial(radio.save_preset, preset_number(body, required=False))),
			"delete_preset": lambda body: partial(self.update_presets, partial(radio.delete_preset, preset_number(body))),
			"hd_step": lambda body: partial(radio.step_hd, direction(body)),
			"volume": lambda body: partial(radio.set_volume, round(number(body, "percent"))),
			"mute": lambda body: partial(radio.set_muted, flag(body, "muted")),
			"pause": lambda body: partial(radio.set_paused, flag(body, "paused")),
			"output": lambda body: partial(radio.set_output, self.output_target(text(body, "target"))),
			"find_speakers": lambda body: self.find_speakers,
		}
		radio.on_status = self.status_changed
		radio.on_message = self.message

	def make_app(self):
		app = aioweb.Application(middlewares=[self.check_password])
		app.router.add_get("/events", self.events)
		app.router.add_get("/stream", self.stream)
		app.router.add_get("/api/state", self.get_state)
		app.router.add_post("/api/{name}", self.command)
		app.router.add_get("/", self.page)
		app.router.add_get("/{path:.+}", self.page)
		app.on_startup.append(self.started)
		app.on_shutdown.append(self.shutting_down)
		app.on_cleanup.append(self.cleaned_up)
		return app

	async def started(self, app):
		self.loop = asyncio.get_running_loop()

	async def shutting_down(self, app):
		"""Ends the event and audio streams, which would otherwise keep the server open."""
		self.stopping = True
		for listener in self.listeners:
			with contextlib.suppress(asyncio.QueueFull):
				listener.put_nowait(None)

	async def cleaned_up(self, app):
		"""Drops queued commands and waits for the running one, so it cannot start a cast after Radio.close."""
		await asyncio.get_running_loop().run_in_executor(None, partial(self.worker.shutdown, wait=True, cancel_futures=True))

	@aioweb.middleware
	async def check_password(self, request, handler):
		if self.password is not None and not self.authorized(request.headers.get("Authorization", "")):
			return aioweb.Response(status=401, text="This radio needs a password.", headers={"WWW-Authenticate": 'Basic realm="sdr", charset="UTF-8"'})
		return await handler(request)

	def authorized(self, header):
		"""Checks a Basic auth header. The user name can be anything."""
		scheme, _, encoded = header.partition(" ")
		if scheme.lower() != "basic":
			return False
		try:
			credentials = base64.b64decode(encoded, validate=True).decode("utf-8")
		except (binascii.Error, UnicodeDecodeError):
			return False
		return hmac.compare_digest(credentials.partition(":")[2].encode(), self.password.encode())

	def output_target(self, name):
		if name in (LOCAL, BROWSERS):
			return name
		for target in self.speakers:
			if target.label == name:
				return target
		raise ValueError(f"No speaker named {name}. Find speakers first.")

	def find_speakers(self):
		"""Runs on the worker thread. Discovery takes about 5 seconds."""
		self.speakers = self.radio.cast_targets(CAST_KINDS)
		count = len(self.speakers)
		if count:
			self.radio.message(f"Found {count} speaker{'' if count == 1 else 's'}.")
		self.radio.notify_status()

	def update_presets(self, action):
		"""Runs action on the worker, then reads the presets again, which it or another program may have changed."""
		action()
		self.presets = self.radio.presets()
		self.radio.notify_status()

	def state(self):
		radio = self.radio
		receiver = radio.receiver
		status = radio.status()
		outputs = ([LOCAL] if receiver.has_sound_card else []) + [BROWSERS] + [target.label for target in self.speakers]
		if status.output not in outputs and status.output != LOCAL:
			# Casting started from the command line, before any search.
			outputs.append(status.output)
		return {
			**dataclasses.asdict(status),
			"bands": [{"name": band.name, "min_mhz": band.min_mhz, "max_mhz": band.max_mhz, "step_mhz": band.step_mhz, "hd": band.hd} for band in receiver.bands],
			"presets": [{"number": number, "label": label, "available": available} for number, label, available in self.presets],
			"outputs": outputs,
			"has_sound_card": receiver.has_sound_card,
		}

	def status_changed(self):
		"""Runs on any thread. Changes come in bursts, so one pending update covers them all."""
		if self.loop is None or self.status_pending:
			return
		self.status_pending = True
		with contextlib.suppress(RuntimeError):
			self.loop.call_soon_threadsafe(self.send_status)

	def send_status(self):
		self.status_pending = False
		self.publish(event_bytes("status", self.state()))

	def message(self, text):
		"""Runs on any thread. Messages also print, as a log for a computer with no screen."""
		print(text)
		if self.loop is None:
			return
		data = event_bytes("message", {"text": text, "error": text.startswith("error: ")})
		with contextlib.suppress(RuntimeError):
			self.loop.call_soon_threadsafe(self.publish, data)

	def publish(self, data):
		for listener in self.listeners:
			with contextlib.suppress(asyncio.QueueFull):
				listener.put_nowait(data)

	async def page(self, request):
		found = static_file(request.match_info.get("path", "index.html"))
		if found is None:
			raise aioweb.HTTPNotFound()
		full, content_type = found
		with open(full, "rb") as file:
			body = file.read()
		return aioweb.Response(body=body, content_type=content_type, charset="utf-8", headers={"Cache-Control": "no-cache"})

	async def get_state(self, request):
		return aioweb.json_response(self.state())

	async def events(self, request):
		response = aioweb.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"})
		await response.prepare(request)
		listener = asyncio.Queue(maxsize=EVENT_BACKLOG)
		self.listeners.add(listener)
		try:
			await response.write(event_bytes("status", self.state()))
			while not self.stopping:
				try:
					data = await asyncio.wait_for(listener.get(), KEEPALIVE_SECONDS)
				except asyncio.TimeoutError:
					data = b": keep open\n\n"
				if data is None:
					break
				await response.write(data)
		except ConnectionResetError:
			pass
		finally:
			self.listeners.discard(listener)
		return response

	async def stream(self, request):
		stream = self.radio.browser_stream
		if stream is None:
			return aioweb.Response(status=409, text="The radio is not playing in browsers.")
		response = aioweb.StreamResponse(headers={"Content-Type": "audio/mpeg", "Cache-Control": "no-store"})
		await response.prepare(request)
		client = LoopQueue(self.loop)
		stream.add_client(client)
		try:
			while stream.running and not self.stopping:
				try:
					data = await asyncio.wait_for(client.queue.get(), STREAM_WAIT_SECONDS)
				except asyncio.TimeoutError:
					continue
				await response.write(data)
		except ConnectionResetError:
			pass
		finally:
			stream.remove_client(client)
		return response

	async def command(self, request):
		parse = self.commands.get(request.match_info["name"])
		if parse is None:
			return aioweb.json_response({"error": "No such command."}, status=404)
		# A page on another site cannot send JSON here without asking first, and the server never agrees.
		if request.content_type != "application/json":
			return aioweb.json_response({"error": "Send the command as JSON."}, status=415)
		try:
			body = await request.json()
		except ValueError:
			return aioweb.json_response({"error": "The body is not JSON."}, status=400)
		if not isinstance(body, dict):
			return aioweb.json_response({"error": "The body must be a JSON object."}, status=400)
		try:
			action = parse(body)
		except ValueError as error:
			return aioweb.json_response({"error": str(error)}, status=400)
		self.worker.submit(self.run_command, action)
		return aioweb.json_response({}, status=202)

	def run_command(self, action):
		try:
			action()
		except Exception as error:
			self.radio.message(f"error: {error}")

	async def serve(self, port, startup):
		"""Serves until the receiver stops. Returns False if the port cannot be used. startup runs on the worker once the port is bound."""
		runner = aioweb.AppRunner(self.make_app())
		await runner.setup()
		try:
			try:
				await aioweb.TCPSite(runner, HOST, port).start()
			except OSError as error:
				print(f"error: Could not start the web server on port {port}: {error}")
				return False
			print(f"Open http://{lan_address()}:{port} in a browser. Press Ctrl+C to quit.")
			await asyncio.get_running_loop().run_in_executor(self.worker, startup)
			while self.radio.receiver.running:
				await asyncio.sleep(RUNNING_CHECK_SECONDS)
			return True
		finally:
			await runner.cleanup()


def run(radio, port, password=None, sonos=None, airplay=None):
	"""Runs the web frontend until Ctrl+C or a receiver error, then stops casting and the receiver.

	Returns False if the server could not start, for example because the port is in use."""
	receiver = radio.receiver
	radio.browsers_available = True
	server = WebServer(radio, password)

	def startup():
		if not receiver.has_sound_card:
			radio.set_output(BROWSERS)
		receiver.start()
		for kind, name in (("sonos", sonos), ("airplay", airplay)):
			if name:
				targets = radio.cast_targets((kind,), name)
				if targets:
					radio.set_output(targets[0])

	try:
		with contextlib.suppress(KeyboardInterrupt):
			return asyncio.run(server.serve(port, startup))
		return True
	finally:
		radio.close()
		receiver.stop()
