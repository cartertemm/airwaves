import { checkboxField, el, mount, speechSettingsFields } from 'audiogame-utils'
import { KEYMAP, VIEW_TITLES } from '../keymap.js'

function sheet(title, onDone, ...children) {
	return el('main', { class: 'sheet' }, el('div', { class: 'sheet-head' }, el('h1', { text: title, tabindex: '-1' }), el('button', { type: 'button', text: 'Close', onClick: onDone })), ...children)
}

export function settingsScreen(root, { radio, speech, onDone }) {
	// The library hides this choice on iOS, where sighted users need it to turn the voice on.
	const speechFields = speechSettingsFields({ speech, modes: ['aria', 'tts'] })
	const setting = (label, key, hint, autoFocus = false) =>
		checkboxField(label, { get: () => radio.settings[key], set: value => radio.setSetting(key, value), hint, autoFocus })
	mount(root, [
		sheet(
			'Settings',
			onDone,
			setting('Receiver sounds', 'sounds', 'Static while seeking, a tone at the end of the band, and the weather alert alarm.', true),
			setting('Key beeps', 'keyBeeps', 'A short beep for front panel keys.'),
			setting('Announce RDS text', 'announceText', 'Say the song and other text the station sends, each time it changes.'),
			el('h2', { text: 'Speech' }),
			speechFields.node,
		),
	])
	return speechFields.dispose
}

export function helpScreen(root, { onDone }) {
	const sections = Object.entries(KEYMAP).flatMap(([view, bindings]) => [
		el('h2', { text: VIEW_TITLES[view] }),
		el('ul', {}, ...bindings.filter(binding => binding.keys.length > 0).map(binding => el('li', { text: `${binding.keyText ?? binding.keys.join(' or ')}: ${binding.label}` }))),
	])
	mount(root, [
		sheet(
			'Help',
			onDone,
			...sections,
			el('h2', { text: 'On iPhone and iPad' }),
			el('p', { text: 'Every command is also a button on the front panel. With a Bluetooth keyboard, turn off VoiceOver Quick Nav (press Left and Right together) so the arrow keys reach the radio. To set the volume while listening in the browser, use the phone\'s volume buttons.' }),
		),
	])
	root.querySelector('h1').focus()
}
