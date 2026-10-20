const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']

export const KEYMAP = {
	panel: [
		{ command: 'togglePause', keys: ['Space'], label: 'Play or pause', beep: true },
		{ command: 'stepDown', keys: ['ArrowLeft'], label: 'Step down', repeat: true, beep: true },
		{ command: 'stepUp', keys: ['ArrowRight'], label: 'Step up', repeat: true, beep: true },
		{ command: 'seekDown', keys: ['Shift+ArrowLeft', 'Ctrl+ArrowLeft'], label: 'Seek down to the previous station', beep: true },
		{ command: 'seekUp', keys: ['Shift+ArrowRight', 'Ctrl+ArrowRight'], label: 'Seek up to the next station', beep: true },
		{ command: 'volumeUp', keys: ['ArrowUp'], label: 'Volume up', repeat: true, beep: true },
		{ command: 'volumeDown', keys: ['ArrowDown'], label: 'Volume down', repeat: true, beep: true },
		{ command: 'toggleMute', keys: ['M'], label: 'Mute or unmute', beep: true },
		{ command: 'openFrequency', keys: ['F'], label: 'Type a frequency', beep: true },
		{ command: 'tunePreset', keys: DIGITS, keyText: '1 to 0', label: 'Tune to that preset. 0 is preset 10', beep: true },
		{ command: 'savePreset', keys: DIGITS.map(digit => `Shift+${digit}`), keyText: 'Shift+1 to Shift+0', label: 'Save this station to that preset, replacing what is there' },
		{ command: 'addPreset', keys: [], label: 'Save this station to the next free preset' },
		{ command: 'nextBand', keys: ['B'], label: 'Next band', beep: true },
		{ command: 'previousBand', keys: ['Shift+B'], label: 'Previous band', beep: true },
		{ command: 'nextHd', keys: ['D'], label: 'Next HD program. The first press checks for HD, and after the last program it goes back to analog', beep: true },
		{ command: 'previousHd', keys: ['Shift+D'], label: 'Previous HD program', beep: true },
		{ command: 'openPresets', keys: ['P'], label: 'Presets' },
		{ command: 'openBands', keys: [], label: 'Choose a band' },
		{ command: 'openHd', keys: [], label: 'Choose an HD program' },
		{ command: 'openOutput', keys: ['O'], label: 'Choose where the sound plays' },
		{ command: 'info', keys: ['I'], label: 'Say what is playing' },
		{ command: 'openSettings', keys: ['S'], label: 'Settings' },
		{ command: 'openHelp', keys: ['H'], label: 'Help' },
	],
	frequency: [
		{ command: 'tune', keys: ['Enter'], label: 'Tune to the frequency typed', local: true },
		{ command: 'close', keys: ['Escape'], label: 'Back to the front panel', local: true },
	],
	list: [
		{ command: 'move', keys: ['ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'], label: 'Move through the list', local: true },
		{ command: 'choose', keys: ['Enter'], label: 'Choose the highlighted item', local: true },
		{ command: 'remove', keys: ['Delete', 'Backspace'], label: 'In presets: clear the highlighted preset (Delete or Backspace)', local: true },
		{ command: 'close', keys: ['Escape'], label: 'Back to the front panel', local: true },
	],
}

export const VIEW_TITLES = { panel: 'Front panel', frequency: 'Frequency entry', list: 'Presets, bands, HD programs, and outputs' }

export function presetNumberOf(combo) {
	const digit = Number(combo.at(-1))
	return digit === 0 ? 10 : digit
}

export function comboOf(event) {
	let key = event.key
	// Shift+1 types "!" on one layout and something else on the next; the physical key is the same.
	const digit = /^Digit(\d)$/.exec(event.code ?? '')
	if (digit) key = digit[1]
	else if (key === ' ' || key === 'Spacebar') key = 'Space'
	else if (key.length === 1) key = key.toUpperCase()
	const parts = []
	if (event.ctrlKey) parts.push('Ctrl')
	if (event.altKey) parts.push('Alt')
	if (event.shiftKey) parts.push('Shift')
	if (event.metaKey) parts.push('Meta')
	parts.push(key)
	return parts.join('+')
}

function isEditable(target) {
	if (!target?.tagName) return false
	return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable === true
}

function activatesNatively(target, combo) {
	if (!target?.tagName) return false
	const activatable = target.tagName === 'BUTTON' || target.tagName === 'A'
	return activatable && (combo === 'Space' || combo === 'Enter')
}

export function createKeymap({ target = globalThis.window, getView, handlers, keymap = KEYMAP, beep = () => {} }) {
	function onKeyDown(event) {
		if (event.defaultPrevented) return
		const bindings = keymap[getView()] ?? []
		const combo = comboOf(event)
		const binding = bindings.find(b => !b.local && b.keys.includes(combo))
		if (!binding) return
		if (isEditable(event.target) || activatesNatively(event.target, combo)) return
		event.preventDefault()
		if (event.repeat && !binding.repeat) return
		if (binding.beep) beep()
		handlers[binding.command]?.(combo)
	}
	target.addEventListener('keydown', onKeyDown)
	return () => target.removeEventListener('keydown', onKeyDown)
}
