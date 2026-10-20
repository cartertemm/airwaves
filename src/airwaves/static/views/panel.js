// The front panel: what is tuned, and every command as a labeled button, so it
// works by touch with or without a screen reader. Keys come from keymap.js.

import { el, mount } from 'audiogame-utils'
import { outputName, signalBars, signalLine } from '../announce.js'

const BAR_COUNT = 4
const ICONS = {
	seekDown: 'M18 6v12l-8.5-6zM9 6v12L.5 12z',
	stepDown: 'M15 6v12L6 12z',
	stepUp: 'M9 6v12l9-6z',
	seekUp: 'M6 6v12l8.5-6zM15 6v12l8.5-6z',
	play: 'M8 5v14l11-7z',
	pause: 'M6 5h4v14H6zM14 5h4v14h-4z',
	mute: 'M4 9v6h4l5 4V5L8 9zm12.5 3 3-3-1.5-1.5-3 3-3-3L10.5 9l3 3-3 3 1.5 1.5 3-3 3 3 1.5-1.5z',
	sound: 'M4 9v6h4l5 4V5L8 9zm11 3a4 4 0 0 0-2-3.5v7a4 4 0 0 0 2-3.5z',
}

function icon(name) {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
	svg.setAttribute('viewBox', '0 0 24 24')
	svg.setAttribute('aria-hidden', 'true')
	const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
	path.setAttribute('d', ICONS[name])
	svg.append(path)
	return svg
}

/** Sets text only when it changed, so screen readers do not re-read the display. */
function setText(node, text) {
	if (node.textContent !== text) node.textContent = text
}

/** props: { radio, commands } where commands maps keymap command names to functions. */
export function panelScreen(root, { radio, commands }) {
	const frequency = el('h1', { class: 'frequency' })
	const station = el('p', { class: 'station' })
	const text = el('p', { class: 'rds' })
	const bars = el('span', { class: 'bars', 'aria-hidden': 'true' }, ...Array.from({ length: BAR_COUNT }, () => el('span')))
	const signalText = el('span')
	const signal = el('p', { class: 'signal' }, bars, signalText)
	const hdBadge = el('span', { class: 'badge hd', text: 'HD' })
	const alertBadge = el('span', { class: 'badge alert' })
	const output = el('p', { class: 'output' })
	const connection = el('p', { class: 'connection' })

	const tuneButton = (command, label, caption) =>
		el('button', { type: 'button', class: 'tune-button', 'aria-label': label, onClick: () => commands[command]() }, icon(command), el('span', { text: caption, 'aria-hidden': 'true' }))
	const button = (text, command) => el('button', { type: 'button', text, onClick: () => commands[command]() })

	const playIcon = el('span', { class: 'icon-slot' })
	const play = el('button', { type: 'button', class: 'play', onClick: () => commands.togglePause() }, playIcon)
	const muteIcon = el('span', { class: 'icon-slot' })
	const mute = el('button', { type: 'button', class: 'mute', 'aria-label': 'Mute', onClick: () => commands.toggleMute() }, muteIcon)
	const volume = el('input', { type: 'range', id: 'volume', min: '0', max: '100', step: '1', 'aria-label': 'Volume', onChange: () => radio.setVolume(Number(volume.value)) })

	function draw() {
		const status = radio.status
		setText(connection, radio.connection === 'open' ? '' : radio.connection === 'closed' ? 'Disconnected' : 'Connecting')
		if (!status) {
			setText(frequency, 'SDR Tuner')
			return
		}
		setText(frequency, status.scanning ? 'Seeking' : status.frequency)
		setText(station, status.station)
		setText(text, status.text)
		setText(signalText, signalLine(status))
		const lit = status.hd_active || status.acars_active ? 0 : signalBars(status.signal_db)
		bars.querySelectorAll('span').forEach((bar, position) => bar.classList.toggle('on', position < lit))
		bars.hidden = status.hd_active || status.acars_active
		hdBadge.hidden = !status.hd_active
		alertBadge.hidden = !status.alert
		setText(alertBadge, status.alert ? `Alert: ${status.alert}` : '')
		setText(output, `Playing on ${outputName(status.output)}`)
		document.title = `${[status.frequency, status.station].filter(Boolean).join(' ')} | SDR Tuner`

		const playing = radio.isPlaying()
		play.setAttribute('aria-label', playing ? 'Pause' : 'Play')
		playIcon.replaceChildren(icon(playing ? 'pause' : 'play'))
		const muted = radio.isMuted()
		mute.setAttribute('aria-pressed', String(muted))
		muteIcon.replaceChildren(icon(muted ? 'mute' : 'sound'))
		volume.disabled = !radio.canSetVolume()
		// Never move a slider the user is holding.
		if (document.activeElement !== volume) volume.value = String(radio.volume())
		volume.setAttribute('aria-valuetext', `${radio.volume()} percent`)
	}

	const panel = el(
		'main',
		{ role: 'application', 'aria-label': 'SDR Tuner front panel', tabindex: '0', autoFocus: true, class: 'panel' },
		el('section', { 'aria-label': 'Display', class: 'display' }, el('div', { class: 'badges' }, hdBadge, alertBadge), frequency, station, text, signal, output, connection),
		el(
			'section',
			{ 'aria-label': 'Tuning', class: 'tuning' },
			tuneButton('seekDown', 'Seek down', 'Seek'),
			tuneButton('stepDown', 'Step down', 'Step'),
			tuneButton('stepUp', 'Step up', 'Step'),
			tuneButton('seekUp', 'Seek up', 'Seek'),
		),
		el(
			'section',
			{ 'aria-label': 'Choose', class: 'choices' },
			button('Frequency', 'openFrequency'),
			button('Presets', 'openPresets'),
			button('Band', 'openBands'),
			button('HD', 'openHd'),
			button('Play on', 'openOutput'),
			button('Save preset', 'addPreset'),
		),
		el('section', { 'aria-label': 'More', class: 'more' }, button("What's playing", 'info'), button('Settings', 'openSettings'), button('Help', 'openHelp')),
		el('section', { 'aria-label': 'Playback', class: 'transport' }, el('div', { class: 'transport-inner' }, play, mute, volume)),
	)

	mount(root, [panel])
	draw()
	return radio.onChange(draw)
}
