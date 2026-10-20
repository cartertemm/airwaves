// The page's radio: holds the last status from the server, decides what to say
// and which sounds to play, and sends commands. In the "browsers" output, play,
// mute, and volume act on this browser's player instead of the server.

import * as say from './announce.js'

const VOLUME_STEP = 5
const DEFAULT_SETTINGS = { sounds: true, keyBeeps: true, announceText: false }

const clampPercent = percent => Math.min(100, Math.max(0, percent))

export function createRadio({ api, player, sfx, speak, storage }) {
	const listeners = new Set()
	const settings = { ...DEFAULT_SETTINGS, ...storage.get('settings', {}) }
	let status = null
	let connection = 'connecting'
	let wantStation = false
	let scanStart = null

	const inBrowser = () => status?.output === 'browsers'
	const currentBand = () => status?.bands.find(band => band.name === status.band)

	function changed() {
		for (const listener of listeners) listener(radio)
	}

	function send(name, body = {}) {
		api.post(name, body).catch(error => speak(error.message, true))
	}

	function announceChanges(previous, next) {
		if (next.scanning && !previous.scanning) {
			sfx.startStatic()
			scanStart = previous
		}
		if (previous.scanning && !next.scanning) sfx.stopStatic()
		const before = previous.scanning ? scanStart ?? previous : previous
		const tuned = !next.scanning && (before.freq_mhz !== next.freq_mhz || before.band !== next.band)
		if (tuned) {
			speak(say.tunedLine(next), true)
			wantStation = !next.station
		} else if (wantStation && next.station && !next.scanning) {
			speak(say.stationLine(next.station))
			wantStation = false
		}
		if (settings.announceText && next.text && next.text !== previous.text && !tuned) speak(say.textLine(next.text))
	}

	function receiveStatus(next) {
		const previous = status
		status = next
		if (previous) announceChanges(previous, next)
		if (previous?.output === 'browsers' && next.output !== 'browsers') player.stop()
		changed()
	}

	function receiveMessage({ text, error }) {
		if (text.startsWith('ALERT:')) {
			sfx.alertTone()
			speak(text, true)
			return
		}
		speak(say.messageLine(text), error)
	}

	function receiveConnection(state) {
		if (state === 'open' && connection === 'lost') speak(say.connectionBackLine())
		if (state === 'lost' && connection !== 'lost') speak(say.connectionLostLine(), true)
		if (state === 'closed') speak(say.connectionClosedLine(), true)
		connection = state
		changed()
	}

	player.onStopped = reason => {
		speak(reason === 'failed' ? say.playFailedLine() : say.streamStoppedLine(), true)
		changed()
	}

	const radio = {
		get status() {
			return status
		},
		get connection() {
			return connection
		},
		get settings() {
			return settings
		},
		onChange(listener) {
			listeners.add(listener)
			return () => listeners.delete(listener)
		},
		start() {
			return api.listen({ onStatus: receiveStatus, onMessage: receiveMessage, onConnection: receiveConnection })
		},

		isPlaying: () => (inBrowser() ? player.listening : !status?.paused),
		isMuted: () => (inBrowser() ? player.muted : Boolean(status?.muted)),
		volume: () => (inBrowser() ? player.volume : status?.volume ?? 0),
		canSetVolume: () => !inBrowser() || player.volumeWorks,

		togglePause() {
			if (!status) return
			if (inBrowser()) {
				if (player.listening) player.stop()
				else player.start()
				speak(say.pauseLine(!player.listening))
				changed()
				return
			}
			const paused = !status.paused
			send('pause', { paused })
			speak(say.pauseLine(paused))
			status = { ...status, paused }
			changed()
		},
		toggleMute() {
			if (!status) return
			if (inBrowser()) {
				player.muted = !player.muted
				speak(say.muteLine(player.muted))
				changed()
				return
			}
			const muted = !status.muted
			send('mute', { muted })
			speak(say.muteLine(muted))
			status = { ...status, muted }
			changed()
		},
		setVolume(percent) {
			if (!status) return
			const level = clampPercent(Math.round(percent))
			if (inBrowser()) {
				player.volume = level
			} else {
				send('volume', { percent: level })
				// Until the server's next status arrives, the next key press builds on this level.
				status = { ...status, volume: level }
			}
			changed()
		},
		changeVolume(direction) {
			if (!status) return
			if (!radio.canSetVolume()) {
				speak(say.phoneVolumeLine(), true)
				return
			}
			const level = clampPercent(radio.volume() + direction * VOLUME_STEP)
			radio.setVolume(level)
			speak(say.volumeLine(level), true)
		},

		step(direction) {
			const band = currentBand()
			if (!band) return
			const next = status.freq_mhz + direction * band.step_mhz
			// Half a step of slack, because the frequencies are floating point.
			if (next < band.min_mhz - band.step_mhz / 2 || next > band.max_mhz + band.step_mhz / 2) {
				sfx.edgeTone()
				return
			}
			send('step', { direction })
		},
		seek: direction => send('seek', { direction }),
		tune: mhz => send('tune', { mhz }),
		chooseBand: name => send('band', { name }),
		changeBand(direction) {
			if (!status) return
			const bands = status.bands
			const index = bands.findIndex(band => band.name === status.band)
			send('band', { name: bands[(index + direction + bands.length) % bands.length].name })
		},
		stepHd: direction => send('hd_step', { direction }),
		chooseHd: program => send('hd', { program }),
		/** Analog, then each HD program. Before HD starts on an HD band, HD1 is offered, because choosing it starts HD. */
		hdChoices() {
			const choices = [{ program: null, label: 'Analog' }]
			if (!status) return choices
			const programs = Object.entries(status.hd_programs).map(([program, name]) => [Number(program), name]).sort(([a], [b]) => a - b)
			for (const [program, name] of programs) choices.push({ program, label: `HD${program + 1} ${name}`.trim() })
			if (programs.length === 0 && currentBand()?.hd) choices.push({ program: 0, label: 'HD1' })
			return choices
		},

		tunePreset(number) {
			if (!status?.presets.some(preset => preset.number === number)) {
				speak(say.emptyPresetLine(number), true)
				return
			}
			send('preset', { number })
		},
		savePreset(number) {
			sfx.click()
			send('save_preset', number === undefined ? {} : { number })
		},
		deletePreset: number => send('delete_preset', { number }),

		setOutput: target => send('output', { target }),
		findSpeakers() {
			speak(say.findingSpeakersLine())
			send('find_speakers')
		},

		info() {
			if (status) speak(say.infoLine(status), true)
		},
		keyBeep() {
			if (settings.keyBeeps) sfx.keyBeep()
		},
		setSetting(key, value) {
			settings[key] = value
			storage.set('settings', settings)
			changed()
		},
	}
	return radio
}
