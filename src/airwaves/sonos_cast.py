import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from .recorder import BITRATE, new_encoder

CHUNK_SECONDS = 0.1
# Data before each ICY metadata block, the title Sonos shows for radio streams.
META_INTERVAL = 16000
# Chunks a slow connection may fall behind before it starts losing audio.
CLIENT_BACKLOG = 50
CLIENT_WAIT_SECONDS = 1
MP3_FRAME_SAMPLES = 1152
DISCOVER_SECONDS = 5
POLL_SECONDS = 0.5
SONOS_PORT = 1400
# Sonos disables skip for a single radio stream. A repeating queue of three copies of it
# enables the skip buttons, and the change in queue position tells which button was pressed.
QUEUE_COPIES = 3
PLAYING_COPY = 1


def find_groups():
	"""Returns the Sonos groups on the network, as they are set up in the Sonos app."""
	import soco
	speakers = soco.discover(timeout=DISCOVER_SECONDS)
	if not speakers:
		return []
	return sorted(next(iter(speakers)).all_groups, key=group_label)


def group_label(group):
	"""Names the coordinator first, and each stereo pair once."""
	names = [group.coordinator.player_name] + [member.player_name for member in group.members]
	return " + ".join(dict.fromkeys(names))


def local_ip(address):
	"""Returns this computer's address on the network that reaches address."""
	with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
		probe.connect((address, SONOS_PORT))
		return probe.getsockname()[0]


def silent_chunk(audio_rate):
	"""Returns whole MP3 frames of silence, about CHUNK_SECONDS long."""
	encoder = new_encoder(audio_rate)
	data = bytes(encoder.encode(np.zeros(audio_rate * 2, dtype=np.int16).tobytes())) + bytes(encoder.flush())
	frame_bytes = 144 * BITRATE * 1000 // audio_rate
	frames = max(1, round(audio_rate * CHUNK_SECONDS / MP3_FRAME_SAMPLES))
	# Take frames from the middle, away from the encoder's start.
	start = len(data) // 2 // frame_bytes * frame_bytes
	return data[start:start + frames * frame_bytes]


def icy_metadata(title):
	# Sonos ends the title at "';", so a plain apostrophe inside it is fine.
	text = f"StreamTitle='{title}';".encode()
	text += b"\0" * (-len(text) % 16)
	return bytes([len(text) // 16]) + text


def station_title(receiver):
	"""Players show the part before " - " as the artist and the rest as the title, so put the station first and the RDS text after."""
	station = " ".join(part for part in (receiver.band.format(receiver.freq_mhz), receiver.rds_name) if part)
	return f"{station} - {receiver.rds_text}" if receiver.rds_text else station


class StreamHandler(BaseHTTPRequestHandler):
	"""Sends the live MP3 stream to one connection."""

	protocol_version = "HTTP/1.0"

	def log_message(self, format, *args):
		pass

	def do_GET(self):
		stream = self.server.stream
		wants_metadata = self.headers.get("Icy-MetaData") == "1"
		self.send_response(200)
		self.send_header("Content-Type", "audio/mpeg")
		if wants_metadata:
			self.send_header("icy-metaint", str(META_INTERVAL))
		self.end_headers()
		client = queue.Queue(maxsize=CLIENT_BACKLOG)
		stream.add_client(client)
		until_metadata = META_INTERVAL
		try:
			while stream.running:
				try:
					data = client.get(timeout=CLIENT_WAIT_SECONDS)
				except queue.Empty:
					continue
				if not wants_metadata:
					self.wfile.write(data)
					continue
				while data:
					part, data = data[:until_metadata], data[until_metadata:]
					self.wfile.write(part)
					until_metadata -= len(part)
					if until_metadata == 0:
						self.wfile.write(icy_metadata(station_title(stream.receiver)))
						until_metadata = META_INTERVAL
		except OSError:
			pass
		finally:
			stream.remove_client(client)


class StreamServer:
	"""Serves a Receiver's audio as a live MP3 stream over HTTP, with the station and RDS text as its title.

	With hold_new_connections, new connections get silence until release() moves them to the live stream."""

	def __init__(self, receiver, audio_rate, host, hold_new_connections=False):
		self.receiver = receiver
		self.audio_rate = audio_rate
		self.host = host
		self.hold_new_connections = hold_new_connections
		self.clients = set()
		self.pending = set()
		self.clients_lock = threading.Lock()
		self.running = False

	def start(self):
		self.running = True
		self.silence = silent_chunk(self.audio_rate)
		self.server = ThreadingHTTPServer((self.host, 0), StreamHandler)
		self.server.daemon_threads = True
		self.server.stream = self
		self.address = f"{self.host}:{self.server.server_address[1]}/stream/"
		for target in (self.server.serve_forever, self.encode):
			threading.Thread(target=target, daemon=True).start()

	def stop(self):
		self.running = False
		self.server.shutdown()

	def add_client(self, client):
		with self.clients_lock:
			(self.pending if self.hold_new_connections else self.clients).add(client)

	def remove_client(self, client):
		with self.clients_lock:
			self.pending.discard(client)
			self.clients.discard(client)

	def waiting(self):
		"""Returns the connections that get silence now."""
		with self.clients_lock:
			return set(self.pending)

	def release(self, waiting):
		"""Moves connections from silence to the live stream."""
		with self.clients_lock:
			released = self.pending & waiting
			self.pending -= released
			self.clients |= released

	def encode(self):
		encoder = new_encoder(self.audio_rate)
		frames = round(self.audio_rate * CHUNK_SECONDS)
		next_time = time.monotonic()
		while self.running:
			audio = self.receiver.read_audio(frames)
			data = bytes(encoder.encode((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()))
			with self.clients_lock:
				sends = [(client, data) for client in self.clients] + [(client, self.silence) for client in self.pending]
			for client, chunk in sends:
				try:
					client.put_nowait(chunk)
				except queue.Full:
					pass
			next_time += CHUNK_SECONDS
			time.sleep(max(0, next_time - time.monotonic()))


class Caster:
	"""Plays a Receiver's audio on a Sonos group, and turns the Sonos skip buttons into scans.

	Override or assign on_skip, on_change, and on_lost to react to Sonos. They run on a background thread."""

	kind = "Sonos"

	def __init__(self, receiver, group, audio_rate):
		self.receiver = receiver
		self.coordinator = group.coordinator
		self.name = group_label(group)
		# New connections get silence until the next poll, because a skip button makes Sonos connect again
		# before the poll can see the skip. Sonos waits for data before it answers, so the poll cannot run sooner.
		self.stream = StreamServer(receiver, audio_rate, local_ip(self.coordinator.ip_address), hold_new_connections=True)
		self.running = False
		self.position = None
		self.status = (False, False)

	def start(self):
		self.running = True
		self.stream.start()
		threading.Thread(target=self.poll, daemon=True).start()
		self.play_mode = self.coordinator.play_mode
		self.coordinator.clear_queue()
		for copy in range(QUEUE_COPIES):
			self.coordinator.add_uri_to_queue(f"x-rincon-mp3radio://{self.stream.address}{copy}.mp3")
		self.coordinator.play_from_queue(PLAYING_COPY)
		# Sonos only takes a play mode while the queue is what plays.
		self.coordinator.play_mode = "REPEAT_ALL"
		self.receiver.local_audio = False

	def stop(self, release=True):
		"""Stops casting and plays on this computer again. release=False leaves Sonos alone, for when it already plays something else."""
		self.running = False
		try:
			if release:
				self.coordinator.stop()
				self.coordinator.play_mode = self.play_mode
				self.coordinator.clear_queue()
		finally:
			self.stream.stop()
			self.receiver.local_audio = True

	def on_skip(self, direction):
		"""Called with 1 or -1 when a Sonos skip button is pressed."""

	def on_change(self):
		"""Called when Sonos is paused, resumed, muted, or unmuted."""

	def on_lost(self):
		"""Called when the group switches to another source. Polling has stopped; call stop(release=False) to leave Sonos alone."""

	def poll(self):
		while self.running:
			time.sleep(POLL_SECONDS)
			# Only connections that arrived before this poll asked Sonos can be released by it.
			waiting = self.stream.waiting()
			try:
				self.check()
			finally:
				self.stream.release(waiting)

	def check(self):
		"""Asks Sonos for its state once: scans on a skip, and reports pauses, mutes, and another source taking over."""
		try:
			track = self.coordinator.get_current_track_info()
			state = self.coordinator.get_current_transport_info()["current_transport_state"]
			muted = self.coordinator.group.mute
		except Exception:
			# Sonos did not answer this time. Ask again on the next poll.
			return
		if not self.running:
			# stop() changes the queue position, which is not a skip.
			return
		# Sonos reports the playing item as x-rincon-mp3radio://http://address/..., so match on the address part.
		if self.stream.address not in track["uri"]:
			# Before Sonos first plays the stream, the previous source still shows.
			if self.position is not None and track["uri"]:
				self.running = False
				self.on_lost()
			return
		position = int(track["playlist_position"])
		if self.position is not None and position != self.position:
			self.on_skip(1 if (position - self.position) % QUEUE_COPIES == 1 else -1)
		self.position = position
		status = (state == "PAUSED_PLAYBACK", muted)
		if status != self.status:
			self.status = status
			self.on_change()

	@property
	def paused(self):
		return self.status[0]

	@paused.setter
	def paused(self, paused):
		if paused:
			self.coordinator.pause()
		else:
			self.coordinator.play()
		self.status = (paused, self.status[1])

	@property
	def muted(self):
		return self.status[1]

	@muted.setter
	def muted(self, muted):
		self.coordinator.group.mute = muted
		self.status = (self.status[0], muted)

	@property
	def volume(self):
		return self.coordinator.group.volume

	@volume.setter
	def volume(self, percent):
		self.coordinator.group.volume = min(100, max(0, percent))
