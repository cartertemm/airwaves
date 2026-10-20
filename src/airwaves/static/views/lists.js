// What each list screen shows, built from the radio's status.

import { bandLabel, outputName, presetLabel } from '../announce.js'

export function presetsList(radio) {
	const presets = radio.status?.presets ?? []
	return {
		title: 'Presets',
		items: presets.map(preset => ({ id: String(preset.number), label: presetLabel(preset), current: false })),
		emptyText: 'No presets yet. On the front panel, press Shift and a number to save this station to that preset.',
		onChoose: id => radio.tunePreset(Number(id)),
		onRemove: id => radio.deletePreset(Number(id)),
		actions: [{ text: 'Save this station to the next free preset', onClick: () => radio.savePreset() }],
	}
}

export function bandsList(radio) {
	const status = radio.status
	return {
		title: 'Band',
		items: (status?.bands ?? []).map(band => ({ id: band.name, label: bandLabel(band), current: band.name === status.band })),
		emptyText: 'No bands.',
		onChoose: name => radio.chooseBand(name),
	}
}

export function hdList(radio) {
	const playing = radio.status?.hd_program ?? null
	return {
		title: 'HD program',
		items: radio.hdChoices().map(choice => ({ id: String(choice.program), label: choice.label, current: choice.program === playing })),
		emptyText: 'No HD programs.',
		onChoose: id => radio.chooseHd(id === 'null' ? null : Number(id)),
	}
}

export function outputList(radio) {
	const status = radio.status
	return {
		title: 'Play on',
		items: (status?.outputs ?? []).map(output => ({ id: output, label: outputName(output), current: output === status.output })),
		emptyText: 'No outputs.',
		onChoose: target => radio.setOutput(target),
		actions: [{ text: 'Find Sonos and AirPlay speakers', onClick: () => radio.findSpeakers() }],
	}
}
