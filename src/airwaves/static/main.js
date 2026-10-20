import { createRouter, createSpeech, createStorage } from 'audiogame-utils'
import { createApi } from './api.js'
import { createKeymap, presetNumberOf } from './keymap.js'
import { bindMediaSession } from './mediasession.js'
import { createPlayer } from './player.js'
import { createRadio } from './radio.js'
import { createSfx } from './sfx.js'
import { frequencyScreen } from './views/frequency.js'
import { listScreen } from './views/list.js'
import { bandsList, hdList, outputList, presetsList } from './views/lists.js'
import { panelScreen } from './views/panel.js'
import { helpScreen, settingsScreen } from './views/settings.js'

const storage = createStorage('sdr')
// The library would use the browser voice on iOS, which talks over VoiceOver.
const speech = createSpeech({ storage, defaultMode: 'aria' })
speech.init()

// iPhone has only ManagedMediaSource, which is not tested with this page, so it plays the stream address.
const feedSource = window.MediaSource?.isTypeSupported('audio/mpeg') ? window.MediaSource : null
const player = createPlayer({ audio: document.getElementById('player'), MediaSource: feedSource, fetch: window.fetch.bind(window), URL: window.URL })
let radio = null
const sfx = createSfx({ isEnabled: () => radio?.settings.sounds ?? true })
radio = createRadio({ api: createApi(), player, sfx, speak: (text, interrupt) => speech.speak(text, interrupt), storage })

const router = createRouter({ root: document.getElementById('app') })
const VIEW_NAMES = new Map([
	[panelScreen, 'panel'],
	[frequencyScreen, 'frequency'],
	[listScreen, 'list'],
])

const back = () => router.back()
const openList = describe => router.go(listScreen, { radio, describe, onDone: back })
const commands = {
	togglePause: () => radio.togglePause(),
	stepDown: () => radio.step(-1),
	stepUp: () => radio.step(1),
	seekDown: () => radio.seek(-1),
	seekUp: () => radio.seek(1),
	volumeUp: () => radio.changeVolume(1),
	volumeDown: () => radio.changeVolume(-1),
	toggleMute: () => radio.toggleMute(),
	openFrequency: () => router.go(frequencyScreen, { radio, speak: text => speech.speak(text, true), onDone: back }),
	tunePreset: combo => radio.tunePreset(presetNumberOf(combo)),
	savePreset: combo => radio.savePreset(presetNumberOf(combo)),
	addPreset: () => radio.savePreset(),
	nextBand: () => radio.changeBand(1),
	previousBand: () => radio.changeBand(-1),
	nextHd: () => radio.stepHd(1),
	previousHd: () => radio.stepHd(-1),
	openPresets: () => openList(presetsList),
	openBands: () => openList(bandsList),
	openHd: () => openList(hdList),
	openOutput: () => openList(outputList),
	info: () => radio.info(),
	openSettings: () => router.go(settingsScreen, { radio, speech, onDone: back }),
	openHelp: () => router.go(helpScreen, { onDone: back }),
}

createKeymap({ target: window, getView: () => VIEW_NAMES.get(router.current) ?? 'other', handlers: commands, beep: () => radio.keyBeep() })
bindMediaSession(radio)

// Browsers start sound and speech only inside a user gesture, so the first tap or key press turns them on.
const GESTURES = ['click', 'keydown', 'touchend']
function unlock() {
	speech.primeTts()
	sfx.unlock()
	for (const type of GESTURES) window.removeEventListener(type, unlock, true)
}
for (const type of GESTURES) window.addEventListener(type, unlock, true)

router.go(panelScreen, { radio, commands })
radio.start()
