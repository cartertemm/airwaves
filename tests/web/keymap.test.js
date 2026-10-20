import assert from 'node:assert/strict'
import { test } from 'node:test'
import { comboOf, createKeymap, KEYMAP, presetNumberOf } from '../../src/airwaves/static/keymap.js'

function fakeTarget() {
	const listeners = []
	return {
		addEventListener: (type, fn) => listeners.push(fn),
		removeEventListener: () => listeners.pop(),
		press(event) {
			const full = { defaultPrevented: false, repeat: false, target: { tagName: 'MAIN' }, preventDefault() { this.defaultPrevented = true }, ...event }
			for (const fn of listeners) fn(full)
			return full
		},
	}
}

function setUp(view = 'panel') {
	const target = fakeTarget()
	const calls = []
	const handlers = new Proxy({}, { get: (_, command) => combo => calls.push([command, combo]) })
	let beeps = 0
	createKeymap({ target, getView: () => view, handlers, beep: () => beeps++ })
	return { target, calls, beeps: () => beeps }
}

test('comboOf names modifiers, letters, digits, and Space', () => {
	assert.equal(comboOf({ key: 'b' }), 'B')
	assert.equal(comboOf({ key: 'B', shiftKey: true }), 'Shift+B')
	assert.equal(comboOf({ key: '!', code: 'Digit1', shiftKey: true }), 'Shift+1')
	assert.equal(comboOf({ key: ' ' }), 'Space')
	assert.equal(comboOf({ key: 'ArrowLeft', ctrlKey: true }), 'Ctrl+ArrowLeft')
})

test('panel keys run their commands and beep', () => {
	const { target, calls, beeps } = setUp()
	target.press({ key: 'ArrowRight' })
	target.press({ key: 'ArrowLeft', shiftKey: true })
	target.press({ key: 'f' })
	target.press({ key: 'h' })
	assert.deepEqual(calls.map(([command]) => command), ['stepUp', 'seekDown', 'openFrequency', 'openHelp'])
	assert.equal(beeps(), 3)
})

test('number keys tune and save presets, 0 is preset 10', () => {
	const { target, calls } = setUp()
	target.press({ key: '3', code: 'Digit3' })
	target.press({ key: ')', code: 'Digit0', shiftKey: true })
	assert.deepEqual(calls, [['tunePreset', '3'], ['savePreset', 'Shift+0']])
	assert.equal(presetNumberOf('Shift+0'), 10)
	assert.equal(presetNumberOf('3'), 3)
})

test('typing in a field and Space on a button keep their normal meaning', () => {
	const { target, calls } = setUp()
	const typed = target.press({ key: 'f', target: { tagName: 'INPUT' } })
	const pressed = target.press({ key: ' ', target: { tagName: 'BUTTON' } })
	assert.deepEqual(calls, [])
	assert.equal(typed.defaultPrevented, false)
	assert.equal(pressed.defaultPrevented, false)
})

test('held keys repeat only where allowed', () => {
	const { target, calls } = setUp()
	target.press({ key: 'ArrowUp', repeat: true })
	target.press({ key: 'm', repeat: true })
	assert.deepEqual(calls.map(([command]) => command), ['volumeUp'])
})

test('keys of other views do nothing on the panel, and local keys are left alone', () => {
	const { target, calls } = setUp('list')
	target.press({ key: 'Enter' })
	assert.deepEqual(calls, [])
})

test('every panel command has a label', () => {
	for (const binding of KEYMAP.panel) assert.ok(binding.label, binding.command)
})
