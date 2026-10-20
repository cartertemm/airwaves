import assert from 'node:assert/strict'
import { test } from 'node:test'
import * as say from '../../src/airwaves/static/announce.js'

const status = {
	frequency: '97.9 MHz', station: 'KXYZ', text: 'Song by Band', signal_db: 23, mer: null,
	hd_active: false, acars_active: false, acars_count: 0, alert: null, output: 'local',
}

test('tuned and station lines', () => {
	assert.equal(say.tunedLine(status), '97.9 MHz, KXYZ.')
	assert.equal(say.tunedLine({ ...status, station: '' }), '97.9 MHz.')
	assert.equal(say.stationLine('KXYZ'), 'KXYZ.')
})

test('signal line for analog, HD, and ACARS', () => {
	assert.equal(say.signalLine(status), 'Signal 23 dB.')
	assert.equal(say.signalLine({ ...status, hd_active: true, mer: [8.6, 7.2] }), 'MER 8.6 and 7.2 dB.')
	assert.equal(say.signalLine({ ...status, hd_active: true }), 'No HD signal yet.')
	assert.equal(say.signalLine({ ...status, acars_active: true, acars_count: 1 }), '1 message.')
})

test('info line says everything a sighted user would see', () => {
	assert.equal(say.infoLine({ ...status, alert: 'Tornado Warning' }), '97.9 MHz, KXYZ. Song by Band. Weather alert: Tornado Warning. Signal 23 dB. Playing on Server speakers.')
	assert.equal(say.infoLine({ ...status, text: '', output: 'browsers' }), '97.9 MHz, KXYZ. Signal 23 dB. Playing on This browser.')
})

test('output names, preset and band labels', () => {
	assert.equal(say.outputName('local'), 'Server speakers')
	assert.equal(say.outputName('Kitchen (Sonos)'), 'Kitchen (Sonos)')
	assert.equal(say.presetLabel({ number: 2, label: '97.9 MHz' }), '2: 97.9 MHz')
	assert.equal(say.bandLabel({ name: 'AM', min_mhz: 0.53, max_mhz: 1.7 }), 'AM, 0.53 to 1.7 MHz')
})

test('messages lose the error prefix', () => {
	assert.equal(say.messageLine('error: Could not start HD.'), 'Could not start HD.')
	assert.equal(say.messageLine('HD found.'), 'HD found.')
})

test('signal bars', () => {
	assert.equal(say.signalBars(0), 0)
	assert.equal(say.signalBars(16), 2)
	assert.equal(say.signalBars(60), 4)
})
