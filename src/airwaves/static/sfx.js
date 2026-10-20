// The page's sounds, made with the Web Audio API so there are no sound files.
// Every method is safe to call when audio is unavailable or sounds are off.

const STATIC_GAIN = 0.12
const TONE_GAIN = 0.2
// The weather radio alarm is 1050 Hz.
const ALERT_HZ = 1050
const ALERT_BEEPS = 3

export function createSfx({
	AudioContextClass = globalThis.AudioContext ?? globalThis.webkitAudioContext,
	isEnabled = () => true,
} = {}) {
	let context = null
	let noiseBuffer = null
	let staticNodes = null

	function ready() {
		return Boolean(context) && isEnabled()
	}

	function tone(frequency, startDelay, duration, type = 'sine') {
		const start = context.currentTime + startDelay
		const oscillator = context.createOscillator()
		const gain = context.createGain()
		oscillator.type = type
		oscillator.frequency.value = frequency
		gain.gain.setValueAtTime(0, start)
		gain.gain.linearRampToValueAtTime(TONE_GAIN, start + 0.01)
		gain.gain.linearRampToValueAtTime(0, start + duration)
		oscillator.connect(gain)
		gain.connect(context.destination)
		oscillator.start(start)
		oscillator.stop(start + duration + 0.02)
	}

	function noise() {
		if (noiseBuffer) return noiseBuffer
		const length = context.sampleRate * 2
		noiseBuffer = context.createBuffer(1, length, context.sampleRate)
		const samples = noiseBuffer.getChannelData(0)
		for (let i = 0; i < length; i++) samples[i] = Math.random() * 2 - 1
		return noiseBuffer
	}

	return {
		/** Call synchronously inside a click or key handler; browsers need a gesture to start audio. */
		unlock() {
			if (!AudioContextClass) return
			context ??= new AudioContextClass()
			if (context.state === 'suspended') context.resume()
		},

		/** A short mechanical click: saving a preset. */
		click() {
			if (!ready()) return
			tone(1800, 0, 0.03, 'square')
		},

		/** A very short, high blip: most key presses. */
		keyBeep() {
			if (!ready()) return
			tone(3000, 0, 0.03, 'triangle')
		},

		/** One low note: a step past the end of the band. */
		edgeTone() {
			if (!ready()) return
			tone(220, 0, 0.18)
		},

		/** Three beeps at the weather radio alarm pitch: a weather alert arrived. */
		alertTone() {
			if (!ready()) return
			for (let beep = 0; beep < ALERT_BEEPS; beep++) tone(ALERT_HZ, beep * 0.4, 0.25)
		},

		/** Looping radio static while a seek runs. Calling it twice is harmless. */
		startStatic() {
			if (!ready() || staticNodes) return
			const source = context.createBufferSource()
			source.buffer = noise()
			source.loop = true
			const filter = context.createBiquadFilter()
			filter.type = 'bandpass'
			filter.frequency.value = 2500
			filter.Q.value = 0.6
			const gain = context.createGain()
			gain.gain.value = STATIC_GAIN
			source.connect(filter)
			filter.connect(gain)
			gain.connect(context.destination)
			source.start()
			staticNodes = { source, gain }
		},

		stopStatic() {
			if (!staticNodes) return
			staticNodes.source.stop()
			staticNodes.gain.disconnect()
			staticNodes = null
		},

		isStaticPlaying() {
			return staticNodes !== null
		},
	}
}
