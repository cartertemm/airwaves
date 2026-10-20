// Type a frequency in MHz. Enter tunes and goes back to the front panel.

import { el, mount } from 'audiogame-utils'

/** props: { radio, speak, onDone } */
export function frequencyScreen(root, { radio, speak, onDone }) {
	const input = el('input', { id: 'frequency', type: 'text', inputmode: 'decimal', autocomplete: 'off', autoFocus: true, value: radio.status ? String(radio.status.freq_mhz) : '' })
	const form = el(
		'form',
		{
			onSubmit: event => {
				event.preventDefault()
				const mhz = Number(input.value.trim())
				if (input.value.trim() === '' || !Number.isFinite(mhz)) {
					speak('Type a frequency in MHz, like 97.9.')
					input.select()
					return
				}
				onDone()
				radio.tune(mhz)
			},
		},
		el('label', { for: 'frequency', text: 'Frequency in MHz' }),
		input,
		el('button', { type: 'submit', class: 'action', text: 'Tune' }),
	)
	mount(root, [
		el('main', { class: 'sheet' }, el('div', { class: 'sheet-head' }, el('h1', { text: 'Frequency' }), el('button', { type: 'button', text: 'Close', onClick: onDone })), form),
	])
	input.select()
}
