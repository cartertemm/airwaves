import asyncio
import concurrent.futures
import socket
import threading
import time

import pyatv
from pyatv.const import Protocol
from pyatv.interface import MediaMetadata
from pyatv.protocols.raop.protocols.airplayv2 import AirPlayV2

from .sonos_cast import SONOS_PORT, StreamServer, station_title

SCAN_SECONDS = 3
CALL_SECONDS = 15
SONOS_CHECK_SECONDS = 1
# AirPlay cannot read a device's volume before streaming, so devices other than Sonos speakers start here.
DEFAULT_VOLUME = 30
LOCAL_HOST = "127.0.0.1"
# A speaker does not answer Sonos requests until it has finished closing the AirPlay session.
REGROUP_DELAY_SECONDS = 3
REGROUP_ATTEMPTS = 5
# ALAC/44100/16/2 in the AirPlay 2 audioFormat bit field.
ALAC_44100_16_2 = 0x40000
CONTENT_TYPE_ALAC = 2
ALAC_ELEMENT_CPE = 1
ALAC_ELEMENT_END = 7


def encode_uncompressed_alac(pcm, frames):
	"""Wraps 16 bit stereo big-endian PCM in an uncompressed ALAC frame.

	Header: element type (3 bits), element instance (4), unused (12), has-size flag (1), shift (2), not-compressed flag (1),
	and sample count (32). The samples follow unchanged, then an end element (3 bits), padded to a byte."""
	header = (ALAC_ELEMENT_CPE << 20) | (1 << 3) | 1
	header = (header << 32) | frames
	bit_count = 55 + len(pcm) * 8 + 3
	value = (header << (len(pcm) * 8 + 3)) | (int.from_bytes(pcm, "big") << 3) | ALAC_ELEMENT_END
	padding = -bit_count % 8
	return (value << padding).to_bytes((bit_count + padding) // 8, "big")


def use_alac():
	"""Makes pyatv send ALAC instead of raw PCM over AirPlay 2. Sonos speakers accept raw PCM but play silence.

	Remove this once pyatv sends ALAC itself."""
	setup_audio_stream = AirPlayV2.setup_audio_stream
	send_audio_packet = AirPlayV2.send_audio_packet

	async def setup_alac_stream(self, control_client_port):
		rtsp_setup = self.rtsp.setup

		async def setup(*args, body=None, **kwargs):
			for stream in (body or {}).get("streams", []):
				stream.update(ct=CONTENT_TYPE_ALAC, audioFormat=ALAC_44100_16_2)
			return await rtsp_setup(*args, body=body, **kwargs)

		self.rtsp.setup = setup
		try:
			return await setup_audio_stream(self, control_client_port)
		finally:
			self.rtsp.setup = rtsp_setup

	async def send_alac_packet(self, transport, rtp_header, audio):
		return await send_audio_packet(self, transport, rtp_header, encode_uncompressed_alac(audio, len(audio) // self.context.frame_size))

	AirPlayV2.setup_audio_stream = setup_alac_stream
	AirPlayV2.send_audio_packet = send_alac_packet


use_alac()


def find_devices():
	"""Returns the AirPlay devices on the network that play audio."""
	async def scan():
		return await pyatv.scan(asyncio.get_running_loop(), timeout=SCAN_SECONDS, protocol=Protocol.RAOP)
	return sorted(asyncio.run(scan()), key=lambda device: device.name)


def sonos_speaker(address):
	"""Returns the Sonos speaker at address, or None if it is not one or soco is not installed."""
	try:
		# Only Sonos speakers listen on this port.
		socket.create_connection((address, SONOS_PORT), timeout=SONOS_CHECK_SECONDS).close()
		import soco
		return soco.SoCo(address)
	except Exception:
		return None


class AirPlayCaster:
	"""Plays a Receiver's audio on an AirPlay device through pyatv.

	AirPlay devices do not send skip button presses back, so on_skip is never called. on_lost is called when the device
	ends the stream itself, for example when it switches to another source. Both run on a background thread."""

	kind = "AirPlay"

	def __init__(self, receiver, device, audio_rate):
		self.receiver = receiver
		self.device = device
		self.name = device.name
		# pyatv reads the stream from this computer, so it only needs to listen locally.
		self.stream = StreamServer(receiver, audio_rate, LOCAL_HOST)
		self.running = False
		self.is_paused = False
		self.is_muted = False
		# For a Sonos speaker, keep its own volume, and remember its group: AirPlay takes it out of the group.
		self.sonos = sonos_speaker(str(device.address))
		self.volume_percent = DEFAULT_VOLUME
		self.sonos_group = None
		if self.sonos:
			self.volume_percent = self.sonos.volume
			group = self.sonos.group
			self.sonos_group = (group.coordinator, [member for member in group.members if member.is_visible])
		self.atv = None
		self.task = None

	def start(self):
		self.running = True
		self.stream.start()
		self.loop = asyncio.new_event_loop()
		threading.Thread(target=self.loop.run_forever, daemon=True).start()
		try:
			self.atv = self.run(pyatv.connect(self.device, self.loop))
			# Set the volume first, or pyatv picks one.
			self.run(self.atv.audio.set_volume(float(self.volume_percent)))
			self.play()
		except Exception:
			self.stop()
			raise
		self.receiver.local_audio = False

	def stop(self, release=True):
		"""Stops casting and plays on this computer again. release=False leaves the Sonos group alone, for when the device already plays something else."""
		self.running = False
		try:
			if self.atv:
				self.end_stream()
				self.run(self.close())
			if release:
				self.restore_group()
		finally:
			self.loop.call_soon_threadsafe(self.loop.stop)
			self.stream.stop()
			self.receiver.local_audio = True

	def restore_group(self):
		"""Puts the speaker's Sonos group back together in the background. The thread is not a daemon, so quitting waits for it."""
		if self.sonos_group:
			threading.Thread(target=self.rejoin).start()

	def rejoin(self):
		coordinator, members = self.sonos_group
		for attempt in range(REGROUP_ATTEMPTS):
			time.sleep(REGROUP_DELAY_SECONDS)
			try:
				grouped = {member.uid for member in coordinator.group.members}
				for member in members:
					if member.uid not in grouped:
						member.join(coordinator)
				return
			except Exception:
				# The speaker is still busy. Try again.
				continue

	async def close(self):
		await asyncio.gather(*self.atv.close())

	def end_stream(self):
		"""Asks pyatv to stop the stream and waits until it has, so the device session closes cleanly."""
		self.run(self.atv.remote_control.stop())
		if self.task:
			concurrent.futures.wait([self.task], timeout=CALL_SECONDS)

	def run(self, coroutine):
		"""Runs a coroutine on the pyatv event loop and waits for it."""
		return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=CALL_SECONDS)

	def play(self):
		# pyatv sets the title once, when the stream starts.
		metadata = MediaMetadata(title=station_title(self.receiver))
		self.task = asyncio.run_coroutine_threadsafe(self.atv.stream.stream_file(f"http://{self.stream.address}airplay.mp3", metadata=metadata), self.loop)
		self.task.add_done_callback(self.stream_ended)

	def stream_ended(self, task):
		# Stopping and pausing also end the stream. Any other end means the device ended it.
		if self.running and not self.is_paused:
			self.running = False
			# This runs on the event loop's thread, and on_lost may call stop(), which waits for that loop.
			threading.Thread(target=self.on_lost, daemon=True).start()

	def on_skip(self, direction):
		"""Matches Caster.on_skip. AirPlay devices do not send skip button presses, so it is never called."""

	def on_change(self):
		"""Matches Caster.on_change. AirPlay devices do not report pauses or mutes, so it is never called."""

	def on_lost(self):
		"""Called when the device ends the stream itself. Call stop() to play on this computer again."""

	@property
	def paused(self):
		return self.is_paused

	@paused.setter
	def paused(self, paused):
		if paused == self.is_paused:
			return
		self.is_paused = paused
		if paused:
			self.end_stream()
		else:
			self.play()

	@property
	def muted(self):
		return self.is_muted

	@muted.setter
	def muted(self, muted):
		# AirPlay has no mute, so mute by setting the volume to 0.
		self.is_muted = muted
		self.run(self.atv.audio.set_volume(0.0 if muted else float(self.volume_percent)))

	@property
	def volume(self):
		return self.volume_percent

	@volume.setter
	def volume(self, percent):
		self.volume_percent = min(100, max(0, percent))
		if not self.is_muted:
			self.run(self.atv.audio.set_volume(float(self.volume_percent)))
