const OUTPUT_NAMES = { local: 'Server speakers', browsers: 'This browser' }
// Signal above the noise floor, in dB, for each bar on the display.
const SIGNAL_BARS_DB = [5, 15, 25, 35]

function plural(count, unit) {
	return `${count} ${unit}${count === 1 ? '' : 's'}`
}

function sentence(text) {
	return /[.!?]$/.test(text) ? text : `${text}.`
}

export function outputName(output) {
	return OUTPUT_NAMES[output] ?? output
}

export function tunedLine(status) {
	return status.station ? `${status.frequency}, ${status.station}.` : `${status.frequency}.`
}

export function stationLine(station) {
	return sentence(station)
}

export function textLine(text) {
	return sentence(text)
}

export function signalLine(status) {
	if (status.acars_active) return `${plural(status.acars_count, 'message')}.`
	if (status.hd_active) return status.mer ? `MER ${status.mer[0].toFixed(1)} and ${status.mer[1].toFixed(1)} dB.` : 'No HD signal yet.'
	return `Signal ${Math.round(status.signal_db)} dB.`
}

export function signalBars(signalDb) {
	return SIGNAL_BARS_DB.filter(threshold => signalDb >= threshold).length
}

export function infoLine(status) {
	const parts = [tunedLine(status)]
	if (status.text) parts.push(textLine(status.text))
	if (status.alert) parts.push(`Weather alert: ${status.alert}.`)
	parts.push(signalLine(status))
	parts.push(`Playing on ${outputName(status.output)}.`)
	return parts.join(' ')
}

export function volumeLine(percent) {
	return `Volume ${percent} percent.`
}

export function muteLine(muted) {
	return muted ? 'Muted.' : 'Unmuted.'
}

export function pauseLine(paused) {
	return paused ? 'Paused.' : 'Playing.'
}

export function messageLine(text) {
	return text.replace(/^error: /, '')
}

export function presetLabel(preset) {
	return `${preset.number}: ${preset.label}`
}

export function bandLabel(band) {
	return `${band.name}, ${band.min_mhz} to ${band.max_mhz} MHz`
}

export function emptyPresetLine(number) {
	return `Preset ${number} is empty.`
}

export function connectionLostLine() {
	return 'Connection to the radio lost. Reconnecting.'
}

export function connectionBackLine() {
	return 'Connected to the radio again.'
}

export function connectionClosedLine() {
	return 'The radio closed the connection. Reload the page.'
}

export function streamStoppedLine() {
	return 'The stream stopped. Press Play to listen again.'
}

export function playFailedLine() {
	return 'The browser could not play the stream.'
}

export function phoneVolumeLine() {
	return "Use the phone's volume buttons."
}

export function findingSpeakersLine() {
	return 'Looking for speakers. This takes about 5 seconds.'
}
