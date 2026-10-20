import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRadio } from '../../src/airwaves/static/radio.js'

const FM = { name: 'FM', min_mhz: 87.9, max_mhz: 107.9, step_mhz: 0.2, hd: true }
const AM = { name: 'AM', min_mhz: 0.53, max_mhz: 1.7, step_mhz: 0.01, hd: false }

function status(changes = {}) {
	return {
		frequency: '97.9 MHz', band: 'FM', freq_mhz: 97.9, station: 'KXYZ', text: '', signal_db: 20, mer: null,
		hd_active: false, hd_program: null, hd_programs: {}, acars_active: false, acars_count: 0, alert: null,
		output: 'local', volume: 50, muted: false, paused: false, scanning: false,
		bands: [AM, FM], presets: [{ number: 1, label: '97.9 MHz', available: true }], outputs: ['local', 'browsers'], has_sound_card: true,
		...changes,
	}
}

function setUp({ volumeWorks = true } = {}) {
	const posts = []
	const spoken = []
	const sounds = []
	const handlers = {}
	const saved = {}
	const api = {
		post: (name, body) => { posts.push([name, body]); return Promise.resolve() },
		listen: callbacks => { Object.assign(handlers, callbacks); return () => {} },
	}
	const player = { listening: false, muted: false, volume: 100, volumeWorks, start() { this.listening = true }, stop() { this.listening = false }, onStopped: null }
	const sfx = new Proxy({}, { get: (_, name) => () => sounds.push(name) })
	const storage = { get: (key, fallback) => saved[key] ?? fallback, set: (key, value) => { saved[key] = structuredClone(value) } }
	const radio = createRadio({ api, player, sfx, speak: (text, interrupt) => spoken.push([text, Boolean(interrupt)]), storage })
	radio.start()
	return { radio, posts, spoken, sounds, handlers, player, saved }
}

test('tuning says the frequency, then the station name once it arrives', () => {
	const { handlers, spoken } = setUp()
	handlers.onStatus(status())
	handlers.onStatus(status({ freq_mhz: 98.1, frequency: '98.1 MHz', station: '' }))
	handlers.onStatus(status({ freq_mhz: 98.1, frequency: '98.1 MHz', station: 'KABC' }))
	handlers.onStatus(status({ freq_mhz: 98.1, frequency: '98.1 MHz', station: 'KABC', signal_db: 30 }))
	assert.deepEqual(spoken, [['98.1 MHz.', true], ['KABC.', false]])
})

test('seeking plays static until the scan ends, then says where it stopped', () => {
	const { handlers, spoken, sounds } = setUp()
	handlers.onStatus(status())
	handlers.onStatus(status({ scanning: true }))
	handlers.onStatus(status({ scanning: false, freq_mhz: 99.5, frequency: '99.5 MHz', station: 'KQRS' }))
	assert.deepEqual(sounds, ['startStatic', 'stopStatic'])
	assert.deepEqual(spoken, [['99.5 MHz, KQRS.', true]])
})

test('a seek that finds nothing stops the static and speaks nothing', () => {
	const { handlers, spoken, sounds } = setUp()
	handlers.onStatus(status())
	handlers.onStatus(status({ scanning: true }))
	handlers.onStatus(status({ scanning: false }))
	assert.deepEqual(sounds, ['startStatic', 'stopStatic'])
	assert.deepEqual(spoken, [])
})

test('RDS text is spoken only when the setting is on', () => {
	const { radio, handlers, spoken, saved } = setUp()
	handlers.onStatus(status())
	handlers.onStatus(status({ text: 'Song one' }))
	radio.setSetting('announceText', true)
	handlers.onStatus(status({ text: 'Song two' }))
	assert.deepEqual(spoken, [['Song two.', false]])
	assert.equal(saved.settings.announceText, true)
})

test('a step past the end of the band plays the edge tone and sends nothing', () => {
	const { radio, handlers, posts, sounds } = setUp()
	handlers.onStatus(status({ freq_mhz: 107.9, frequency: '107.9 MHz' }))
	radio.step(1)
	radio.step(-1)
	assert.deepEqual(sounds, ['edgeTone'])
	assert.deepEqual(posts, [['step', { direction: -1 }]])
})

test('band keys go round the list of bands', () => {
	const { radio, handlers, posts } = setUp()
	handlers.onStatus(status())
	radio.changeBand(1)
	radio.changeBand(-1)
	assert.deepEqual(posts, [['band', { name: 'AM' }], ['band', { name: 'AM' }]])
})

test('volume keys on the server output change by 5 and speak the level', t => {
	t.mock.timers.enable({ apis: ['setTimeout'] })
	const { radio, handlers, posts, spoken } = setUp()
	handlers.onStatus(status())
	radio.changeVolume(1)
	radio.changeVolume(1)
	assert.deepEqual(spoken.at(-1), ['Volume 60 percent.', true])
	t.mock.timers.tick(200)
	assert.deepEqual(posts, [['volume', { percent: 55 }], ['volume', { percent: 60 }]])
})

test('held volume keys send one command per 200 ms, and the last level after the burst', t => {
	t.mock.timers.enable({ apis: ['setTimeout'] })
	const { radio, handlers, posts } = setUp()
	handlers.onStatus(status())
	radio.changeVolume(1)
	radio.changeVolume(1)
	radio.changeVolume(1)
	assert.deepEqual(posts, [['volume', { percent: 55 }]])
	t.mock.timers.tick(200)
	assert.deepEqual(posts, [['volume', { percent: 55 }], ['volume', { percent: 65 }]])
	t.mock.timers.tick(1000)
	assert.equal(posts.length, 2)
})

test('in the browser, play, mute, and volume act on the audio element', () => {
	const { radio, handlers, posts, player } = setUp()
	handlers.onStatus(status({ output: 'browsers' }))
	radio.togglePause()
	radio.toggleMute()
	radio.changeVolume(-1)
	assert.equal(player.listening, true)
	assert.equal(player.muted, true)
	assert.equal(player.volume, 95)
	assert.deepEqual(posts, [])
})

test('play and pause act only when needed, in the browser and on the server', () => {
	const { radio, handlers, posts, player } = setUp()
	handlers.onStatus(status({ output: 'browsers' }))
	radio.pause()
	assert.equal(player.listening, false)
	radio.play()
	radio.play()
	assert.equal(player.listening, true)
	radio.pause()
	radio.pause()
	assert.equal(player.listening, false)
	handlers.onStatus(status({ output: 'local' }))
	radio.play()
	assert.deepEqual(posts, [])
	radio.pause()
	radio.pause()
	radio.play()
	radio.play()
	assert.deepEqual(posts, [['pause', { paused: true }], ['pause', { paused: false }]])
})

test('the browser pausing the audio is not spoken', () => {
	const { handlers, spoken, player } = setUp()
	handlers.onStatus(status({ output: 'browsers' }))
	player.onStopped('paused')
	assert.deepEqual(spoken, [])
})

test('quick repeat presses of pause and mute on the server send the new value each time', () => {
	const { radio, handlers, posts } = setUp()
	handlers.onStatus(status())
	radio.togglePause()
	radio.togglePause()
	radio.toggleMute()
	radio.toggleMute()
	assert.deepEqual(posts, [['pause', { paused: true }], ['pause', { paused: false }], ['mute', { muted: true }], ['mute', { muted: false }]])
})

test('where the page cannot set the volume, the volume keys say so', () => {
	const { radio, handlers, spoken } = setUp({ volumeWorks: false })
	handlers.onStatus(status({ output: 'browsers' }))
	radio.changeVolume(1)
	assert.deepEqual(spoken.at(-1), ["Use the phone's volume buttons.", true])
	assert.equal(radio.canSetVolume(), false)
})

test('only a speaker on the network counts as casting', () => {
	const { radio, handlers } = setUp()
	assert.equal(radio.isCasting(), false)
	handlers.onStatus(status({ output: 'local' }))
	assert.equal(radio.isCasting(), false)
	handlers.onStatus(status({ output: 'browsers' }))
	assert.equal(radio.isCasting(), false)
	handlers.onStatus(status({ output: 'Kitchen (sonos)' }))
	assert.equal(radio.isCasting(), true)
})

test('leaving the browser output stops listening', () => {
	const { radio, handlers, player } = setUp()
	handlers.onStatus(status({ output: 'browsers' }))
	radio.togglePause()
	handlers.onStatus(status({ output: 'local' }))
	assert.equal(player.listening, false)
})

test('weather alerts sound the alarm, then speak the text and interrupt', t => {
	t.mock.timers.enable({ apis: ['setTimeout'] })
	const { handlers, spoken, sounds } = setUp()
	handlers.onMessage({ text: 'ALERT: Tornado Warning', error: false })
	handlers.onMessage({ text: 'error: Could not start HD.', error: true })
	assert.deepEqual(sounds, ['alertTone'])
	assert.deepEqual(spoken, [['Could not start HD.', true]])
	t.mock.timers.tick(1200)
	assert.deepEqual(spoken, [['Could not start HD.', true], ['ALERT: Tornado Warning', true]])
})

test('with sounds off, the alert text is spoken at once', () => {
	const { radio, handlers, spoken, sounds } = setUp()
	radio.setSetting('sounds', false)
	handlers.onMessage({ text: 'ALERT: Tornado Warning', error: false })
	assert.deepEqual(spoken, [['ALERT: Tornado Warning', true]])
	assert.deepEqual(sounds, ['alertTone'])
})

test('a lost connection is said once, and its return once', () => {
	const { handlers, spoken } = setUp()
	handlers.onConnection('open')
	handlers.onConnection('lost')
	handlers.onConnection('lost')
	handlers.onConnection('open')
	handlers.onConnection('open')
	assert.deepEqual(spoken.map(([text]) => text), ['Connection to the radio lost. Reconnecting.', 'Connected to the radio again.'])
})

test('preset keys before the first status say nothing', () => {
	const { radio, posts, spoken } = setUp()
	radio.tunePreset(1)
	assert.deepEqual(spoken, [])
	assert.deepEqual(posts, [])
})

test('presets: an empty slot is said, saving posts the slot', () => {
	const { radio, handlers, posts, spoken, sounds } = setUp()
	handlers.onStatus(status())
	radio.tunePreset(4)
	radio.tunePreset(1)
	radio.savePreset(3)
	radio.savePreset()
	assert.deepEqual(spoken, [['Preset 4 is empty.', true]])
	assert.deepEqual(posts, [['preset', { number: 1 }], ['save_preset', { number: 3 }], ['save_preset', {}]])
	assert.deepEqual(sounds, ['click', 'click'])
})

test('HD choices list analog and each program, or HD1 before HD starts on FM', () => {
	const { radio, handlers } = setUp()
	handlers.onStatus(status())
	assert.deepEqual(radio.hdChoices(), [{ program: null, label: 'Analog' }, { program: 0, label: 'HD1' }])
	handlers.onStatus(status({ hd_active: true, hd_program: 1, hd_programs: { 1: 'Two', 0: 'One' } }))
	assert.deepEqual(radio.hdChoices(), [{ program: null, label: 'Analog' }, { program: 0, label: 'HD1 One' }, { program: 1, label: 'HD2 Two' }])
	handlers.onStatus(status({ band: 'AM', freq_mhz: 1.0, frequency: '1000 kHz' }))
	assert.deepEqual(radio.hdChoices(), [{ program: null, label: 'Analog' }])
})

test('a refused command is spoken', async () => {
	const spoken = []
	const radio = createRadio({
		api: { post: () => Promise.reject(new Error('mhz must be a number.')), listen: () => () => {} },
		player: {},
		sfx: {},
		speak: (text, interrupt) => spoken.push([text, interrupt]),
		storage: { get: (key, fallback) => fallback, set() {} },
	})
	radio.tune(Number.NaN)
	await new Promise(resolve => setTimeout(resolve, 0))
	assert.deepEqual(spoken, [['mhz must be a number.', true]])
})
