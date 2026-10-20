import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPlayer } from '../../src/airwaves/static/player.js'

function fakeAudio({ volumeWorks = true, playResult = Promise.resolve() } = {}) {
	const listeners = {}
	let volume = 1
	return {
		src: '', muted: false, paused: true, ended: false, loads: 0,
		get volume() { return volume },
		set volume(value) { if (volumeWorks) volume = value },
		play() { this.paused = false; return playResult },
		pause() { this.paused = true },
		load() { this.loads++ },
		removeAttribute(name) { if (name === 'src') this.src = '' },
		addEventListener(type, fn) { listeners[type] = fn },
		fire(type) { listeners[type]() },
	}
}

test('start plays a fresh stream address and stop clears it', () => {
	const audio = fakeAudio()
	const player = createPlayer({ audio })
	player.start()
	assert.equal(player.listening, true)
	assert.match(audio.src, /^stream\?\d+$/)
	player.stop()
	assert.equal(player.listening, false)
	assert.equal(audio.src, '')
})

test('volume in percent, and whether the browser lets the page set it', () => {
	const player = createPlayer({ audio: fakeAudio() })
	player.volume = 40
	assert.equal(player.volume, 40)
	assert.equal(player.volumeWorks, true)
	assert.equal(createPlayer({ audio: fakeAudio({ volumeWorks: false }) }).volumeWorks, false)
})

test('a stream that ends while listening reports stopped', () => {
	const audio = fakeAudio()
	const player = createPlayer({ audio })
	const reasons = []
	player.onStopped = reason => reasons.push(reason)
	audio.fire('ended')
	player.start()
	audio.fire('error')
	assert.deepEqual(reasons, ['stopped'])
	assert.equal(player.listening, false)
})

test('a refused play reports failed, but an aborted one does not', async () => {
	const refused = createPlayer({ audio: fakeAudio({ playResult: Promise.reject(Object.assign(new Error(), { name: 'NotAllowedError' })) }) })
	const reasons = []
	refused.onStopped = reason => reasons.push(reason)
	refused.start()
	const aborted = createPlayer({ audio: fakeAudio({ playResult: Promise.reject(Object.assign(new Error(), { name: 'AbortError' })) }) })
	aborted.onStopped = reason => reasons.push(reason)
	aborted.start()
	await new Promise(resolve => setTimeout(resolve, 0))
	assert.deepEqual(reasons, ['failed'])
})

test('the browser pausing the audio while listening reports paused, but stop does not', () => {
	const audio = fakeAudio()
	const player = createPlayer({ audio })
	const reasons = []
	player.onStopped = reason => reasons.push(reason)
	player.start()
	audio.fire('pause')
	assert.equal(player.listening, false)
	assert.deepEqual(reasons, ['paused'])
	player.start()
	player.stop()
	audio.fire('pause')
	assert.deepEqual(reasons, ['paused'])
})

test('a late pause event from stop does not stop a stream that just restarted', () => {
	const audio = fakeAudio()
	const player = createPlayer({ audio })
	const reasons = []
	player.onStopped = reason => reasons.push(reason)
	player.start()
	player.stop()
	player.start()
	audio.fire('pause')
	assert.equal(player.listening, true)
	assert.deepEqual(reasons, [])
	audio.fire('pause')
	assert.equal(player.listening, false)
	assert.deepEqual(reasons, ['paused'])
})

test('a pause event at the end of the stream is left to the ended event', () => {
	const audio = fakeAudio()
	const player = createPlayer({ audio })
	const reasons = []
	player.onStopped = reason => reasons.push(reason)
	player.start()
	audio.ended = true
	audio.fire('pause')
	audio.fire('ended')
	assert.deepEqual(reasons, ['stopped'])
})
