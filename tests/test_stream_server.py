import queue

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
