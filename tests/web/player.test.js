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

function ranges(list) {
	return { length: list.length, start: index => list[index][0], end: index => list[index][1] }
}

function fakeFeed() {
	const sources = []
	const requests = []
	class MediaSource {
		constructor() {
			this.listeners = {}
			this.buffer = null
			sources.push(this)
		}
		addEventListener(type, fn) { this.listeners[type] = fn }
		open() { this.listeners.sourceopen() }
		addSourceBuffer(type) {
			const listeners = {}
			this.buffer = {
				type, updating: false, appended: [], removed: [], held: [],
				get buffered() { return ranges(this.held) },
				appendBuffer(data) { this.updating = true; this.appended.push(data) },
				remove(start, end) { this.updating = true; this.removed.push([start, end]) },
				addEventListener(name, fn) { listeners[name] = fn },
				finish(held) { this.updating = false; if (held) this.held = held; listeners.updateend() },
			}
			return this.buffer
		}
	}
	function fetch(address, { signal }) {
		const waiting = []
		const reads = []
		const request = {
			address, signal,
			send(value) { const read = { value, done: false }; waiting.length ? waiting.shift()(read) : reads.push(read) },
			end() { const read = { done: true }; waiting.length ? waiting.shift()(read) : reads.push(read) },
		}
		requests.push(request)
		const reader = { read: () => (reads.length ? Promise.resolve(reads.shift()) : new Promise(resolve => waiting.push(resolve))) }
		return Promise.resolve({ ok: true, body: { getReader: () => reader } })
	}
	const URL = { createObjectURL: () => 'blob:feed', revokeObjectURL() {} }
	return { MediaSource, fetch, URL, sources, requests }
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0))

test('with a media source, the player feeds the stream to the audio one piece at a time', async () => {
	const audio = fakeAudio()
	const feed = fakeFeed()
	const player = createPlayer({ audio, ...feed })
	player.start()
	assert.equal(audio.src, 'blob:feed')
	feed.sources[0].open()
	const buffer = feed.sources[0].buffer
	assert.equal(buffer.type, 'audio/mpeg')
	await settle()
	assert.match(feed.requests[0].address, /^stream\?\d+$/)
	feed.requests[0].send('a')
	feed.requests[0].send('b')
	await settle()
	assert.deepEqual(buffer.appended, ['a'])
	buffer.finish([[0, 0.1]])
	assert.deepEqual(buffer.appended, ['a', 'b'])
})

test('a fed player skips ahead when it falls behind the newest audio', async () => {
	const audio = fakeAudio()
	audio.currentTime = 2
	const feed = fakeFeed()
	createPlayer({ audio, ...feed }).start()
	feed.sources[0].open()
	await settle()
	feed.requests[0].send('a')
	await settle()
	feed.sources[0].buffer.finish([[0, 4]])
	assert.equal(audio.currentTime, 3.7)
})

test('a fed player removes audio it has already played', async () => {
	const audio = fakeAudio()
	audio.currentTime = 12
	const feed = fakeFeed()
	createPlayer({ audio, ...feed }).start()
	feed.sources[0].open()
	await settle()
	feed.requests[0].send('a')
	await settle()
	const buffer = feed.sources[0].buffer
	buffer.finish([[0, 12.2]])
	assert.deepEqual(buffer.removed, [[0, 11]])
})

test('a fed stream that ends reports stopped, and stop cancels the request', async () => {
	const feed = fakeFeed()
	const player = createPlayer({ audio: fakeAudio(), ...feed })
	const reasons = []
	player.onStopped = reason => reasons.push(reason)
	player.start()
	feed.sources[0].open()
	await settle()
	feed.requests[0].end()
	await settle()
	assert.deepEqual(reasons, ['stopped'])
	player.start()
	feed.sources[1].open()
	await settle()
	player.stop()
	assert.equal(feed.requests[1].signal.aborted, true)
	feed.requests[1].end()
	await settle()
	assert.deepEqual(reasons, ['stopped'])
})
