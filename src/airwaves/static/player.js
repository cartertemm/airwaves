// Plays the radio's MP3 stream in this browser through one <audio> element.

const PERCENT = 100

/** Some browsers (iPhone Safari) ignore a page setting the volume. */
function canSetVolume(audio) {
	const old = audio.volume
	audio.volume = 0.5
	const works = audio.volume === 0.5
	audio.volume = old
	return works
}

/** Assign onStopped(reason) to hear when listening ends by itself: 'failed' if the browser refused to play, 'stopped' if the stream ended, 'paused' if the browser or the system paused the audio. */
export function createPlayer({ audio }) {
	let listening = false
	// Each start gets a new token, so a late refusal from an older play() is ignored.
	let token = 0
	// Pause events the page caused with stop(), which the browser delivers later.
	let pendingPauses = 0

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
			audio.src = `stream?${Date.now()}`
			audio.play().catch(error => {
				if (mine !== token || error.name === 'AbortError') return
				player.stop()
				player.onStopped?.('failed')
			})
		},
		stop() {
			listening = false
			token++
			if (!audio.paused) pendingPauses++
			audio.pause()
			audio.removeAttribute('src')
			audio.load()
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
