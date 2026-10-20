const PERCENT = 100
const MP3 = 'audio/mpeg'
const LIVE_LAG_SECONDS = 1
const LIVE_TARGET_SECONDS = 0.3
const KEEP_SECONDS = 10
const KEEP_BEHIND_SECONDS = 1

/** Some browsers (iPhone Safari) ignore a page setting the volume. */
function canSetVolume(audio) {
	const old = audio.volume
	audio.volume = 0.5
	const works = audio.volume === 0.5
	audio.volume = old
	return works
}

/**
 * With a MediaSource, the page feeds the stream to the audio itself. A browser playing the stream address directly holds several seconds of it before it plays (6.6 s in Edge), so a new station is heard late.
 */
export function createPlayer({ audio, MediaSource = null, fetch = null, URL = null }) {
	let listening = false
	// Each start gets a new token, so a late refusal from an older play() is ignored.
	let token = 0
	// Pause events the page caused with stop(), which the browser delivers later.
	let pendingPauses = 0
	let request = null
	let sourceAddress = null

	function feed(address, mine) {
		const source = new MediaSource()
		request = new AbortController()
		const { signal } = request
		sourceAddress = URL.createObjectURL(source)
		audio.src = sourceAddress
		source.addEventListener('sourceopen', () => {
			if (mine !== token) return
			const buffer = source.addSourceBuffer(MP3)
			const pieces = []
			const next = () => {
				if (mine !== token || buffer.updating) return
				const { buffered } = buffer
				if (buffered.length) {
					const newest = buffered.end(buffered.length - 1)
					if (newest - audio.currentTime > LIVE_LAG_SECONDS) audio.currentTime = newest - LIVE_TARGET_SECONDS
					const oldest = buffered.start(0)
					// The browser refuses new audio once the buffer is full, after a few minutes of this stream.
					if (audio.currentTime - oldest > KEEP_SECONDS) {
						buffer.remove(oldest, audio.currentTime - KEEP_BEHIND_SECONDS)
						return
					}
				}
				if (pieces.length) buffer.appendBuffer(pieces.shift())
			}
			buffer.addEventListener('updateend', next)
			read(fetch(address, { signal }), pieces, next, mine)
		})
	}

	async function read(response, pieces, next, mine) {
		try {
			const result = await response
			if (result.ok) {
				const reader = result.body.getReader()
				for (;;) {
					const { value, done } = await reader.read()
					if (mine !== token || done) break
					pieces.push(value)
					next()
				}
			}
		} catch {}
		if (mine === token) streamStopped()
	}

	const player = {
		onStopped: null,
		volumeWorks: canSetVolume(audio),
		get listening() {
			return listening
		},
		get muted() {
			return audio.muted
		},
		set muted(muted) {
			audio.muted = muted
		},
		get volume() {
			return Math.round(audio.volume * PERCENT)
		},
		set volume(percent) {
			audio.volume = percent / PERCENT
		},
		start() {
			listening = true
			const mine = ++token
			// A new address each time, so the browser does not replay old audio from its cache.
			const address = `stream?${Date.now()}`
			if (MediaSource) feed(address, mine)
			else audio.src = address
			audio.play().catch(error => {
				if (mine !== token || error.name === 'AbortError') return
				player.stop()
				player.onStopped?.('failed')
			})
		},
		stop() {
			listening = false
			token++
			request?.abort()
			request = null
			if (!audio.paused) pendingPauses++
			audio.pause()
			audio.removeAttribute('src')
			audio.load()
			if (sourceAddress) URL.revokeObjectURL(sourceAddress)
			sourceAddress = null
		},
	}

	function streamStopped() {
		if (!listening) return
		player.stop()
		player.onStopped?.('stopped')
	}
	audio.addEventListener('pause', () => {
		if (pendingPauses > 0) {
			pendingPauses--
			return
		}
		if (!listening || audio.ended) return
		listening = false
		token++
		player.onStopped?.('paused')
	})
	audio.addEventListener('error', streamStopped)
	audio.addEventListener('ended', streamStopped)
	return player
}
