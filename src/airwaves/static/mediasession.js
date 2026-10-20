// Lock screen, headset, and keyboard media keys, while this browser plays the radio.

export function bindMediaSession(radio, { mediaSession = globalThis.navigator?.mediaSession, MediaMetadataClass = globalThis.MediaMetadata } = {}) {
	if (!mediaSession || !MediaMetadataClass) return () => {}
	const actions = {
		play: () => radio.togglePause(),
		pause: () => radio.togglePause(),
		previoustrack: () => radio.seek(-1),
		nexttrack: () => radio.seek(1),
	}
	for (const [action, handler] of Object.entries(actions)) {
		try {
			mediaSession.setActionHandler(action, handler)
		} catch {
			// This browser does not support that action.
		}
	}
	let last = ''
	function update() {
		const status = radio.status
		if (!status) return
		const next = JSON.stringify([status.frequency, status.station, status.text])
		if (next === last) return
		last = next
		mediaSession.metadata = new MediaMetadataClass({ title: status.text || status.station || status.frequency, artist: [status.frequency, status.station].filter(Boolean).join(' '), album: 'SDR Tuner' })
	}
	return radio.onChange(update)
}
