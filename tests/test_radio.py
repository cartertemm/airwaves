import numpy as np

from conftest import FakeCaster, FakeReceiver

from airwaves import config, sdr
from airwaves.radio import BROWSERS, LOCAL, CastTarget, Preset, Radio


def watch(radio):
	"""Collects the radio's messages, and its status at each status change."""
	messages = []
	statuses = []
	radio.on_message = messages.append
	radio.on_status = lambda: statuses.append(radio.status())
	return messages, statuses


def test_status_shows_the_hd_program(receiver):
	receiver.hd_start()
	receiver.select_hd_program(1)
	status = Radio(receiver).status()
	assert status.frequency == "97.9 MHz HD2 of 2"
	assert status.station == "Two"
	assert status.band == "FM"
	assert status.output == "local"
	assert not status.hd_lost


def test_status_names_the_caster(receiver):
	radio = Radio(receiver)
	radio.caster = FakeCaster(receiver)
	status = radio.status()
	assert status.output == "Kitchen (Sonos)"
	assert status.volume == 30


def test_tune_outside_the_bands_is_an_error(receiver):
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.tune(200)
	assert messages == ["error: Frequency not in range."]
	assert receiver.freq_mhz == 97.9


def test_tune_band_goes_to_the_start_of_the_band(receiver):
	Radio(receiver).tune_band("AM")
	assert receiver.freq_mhz == 0.53


def test_step_stays_in_the_band(receiver):
	radio = Radio(receiver)
	radio.step(1)
	assert receiver.freq_mhz == 98.0
	receiver.tune(108.0)
	radio.step(1)
	assert receiver.freq_mhz == 108.0


def test_seek_shows_scanning_then_no_station(receiver):
	radio = Radio(receiver)
	messages, statuses = watch(radio)
	radio.seek(1)
	assert receiver.seeks == [1]
	assert statuses[0].scanning
	assert messages == ["No other station found."]
	assert not radio.status().scanning


def test_select_hd_starts_hd_and_plays_the_program(receiver):
	radio = Radio(receiver)
	radio.select_hd(1)
	assert receiver.hd_active
	assert receiver.hd_program == 1
	radio.select_hd(None)
	assert not receiver.hd_active


def test_select_hd_needs_fm(receiver):
	receiver.tune(1.0)
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.select_hd(0)
	assert messages == ["HD works only on FM."]
	assert not receiver.hd_active


def test_presets_save_list_and_choose(receiver):
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.save_preset()
	assert messages[-1] == "97.9 MHz saved to preset 1"
	radio.save_preset()
	assert messages[-1] == "97.9 MHz is already preset 1."
	config.save("2", "200", config.PRESETS)
	assert radio.presets() == [(1, "97.9 MHz", True), (2, "200 (not available)", False)]
	receiver.tune(101.1)
	radio.choose_preset(1)
	assert receiver.freq_mhz == 97.9
	radio.choose_preset(2)
	assert messages[-1] == "error: Preset 2 is not available."


def test_save_preset_to_a_slot_replaces_it(receiver):
	radio = Radio(receiver)
	messages, _ = watch(radio)
	config.save("3", "101.1", config.PRESETS)
	radio.save_preset(3)
	assert config.presets() == {3: "97.9"}
	assert messages[-1] == "97.9 MHz saved to preset 3"


def test_delete_preset(receiver):
	radio = Radio(receiver)
	messages, _ = watch(radio)
	config.save("1", "97.9", config.PRESETS)
	config.save("2", "101.1", config.PRESETS)
	radio.delete_preset(1)
	assert config.presets() == {2: "101.1"}
	assert messages[-1] == "Cleared preset 1."
	radio.delete_preset(1)
	assert messages[-1] == "Preset 1 is empty."


def test_preset_text_round_trips():
	assert Preset.parse("99.9 HD2") == Preset(99.9, 1)
	assert Preset(99.9, 1).text() == "99.9 HD2"
	assert Preset.parse("99.9 HD0") is None


def test_volume_is_saved_only_for_the_receiver(receiver):
	radio = Radio(receiver)
	radio.set_volume(70)
	assert receiver.volume == 70
	assert config.load()["volume"] == "70"
	caster = FakeCaster(receiver)
	radio.caster = caster
	radio.change_volume(-10)
	assert caster.volume == 20
	assert config.load()["volume"] == "70"


def test_alert_mode_unmutes_on_an_alert(receiver):
	radio = Radio(receiver, alert_mode=True)
	messages, _ = watch(radio)
	assert receiver.muted
	radio.announce_alert(sdr.Alert("Tornado Warning"))
	assert not receiver.muted
	assert messages == ["ALERT: Tornado Warning"]


def test_alert_mode_silences_browsers_until_an_alert(receiver):
	radio = Radio(receiver, alert_mode=True)
	receiver.read_audio = lambda frame_count: np.ones((frame_count, 2), dtype=np.float32)
	assert not radio.browser_audio(4).any()
	radio.announce_alert(sdr.Alert("Tornado Warning"))
	assert radio.browser_audio(4).all()


def kitchen(receiver):
	return CastTarget("Kitchen (Sonos)", ["Kitchen"], lambda: FakeCaster(receiver))


def test_browsers_output_streams_until_local(receiver):
	radio = Radio(receiver)
	receiver.paused = True
	radio.set_output(BROWSERS)
	stream = radio.browser_stream
	assert stream.running
	assert not receiver.local_audio
	assert not receiver.paused
	assert radio.status().output == BROWSERS
	radio.set_output(LOCAL)
	assert radio.browser_stream is None
	assert not stream.running
	assert receiver.local_audio
	assert radio.status().output == LOCAL


def test_local_output_needs_a_sound_card(receiver):
	receiver.has_sound_card = False
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.set_output(LOCAL)
	assert messages == ["error: This computer has no sound card."]


def test_casting_stops_the_browser_stream(receiver):
	radio = Radio(receiver)
	radio.set_output(BROWSERS)
	radio.set_output(kitchen(receiver))
	assert radio.browser_stream is None
	assert radio.caster.started
	assert radio.status().output == "Kitchen (Sonos)"
	radio.set_output(LOCAL)
	assert radio.caster is None
	assert receiver.local_audio


def test_lost_cast_plays_in_browsers_without_a_sound_card(receiver):
	receiver.has_sound_card = False
	radio = Radio(receiver)
	radio.browsers_available = True
	messages, _ = watch(radio)
	radio.set_output(kitchen(receiver))
	radio.caster.on_lost()
	try:
		assert radio.browser_stream is not None
		assert messages[-1] == "Sonos: Kitchen stopped playing the radio. Playing in the browser again."
	finally:
		radio.close()
	assert radio.browser_stream is None


def broken():
	raise OSError("no route")


BROKEN = CastTarget("Kitchen (Sonos)", ["Kitchen"], broken)


def test_failed_cast_plays_in_browsers_without_a_sound_card(receiver):
	receiver.has_sound_card = False
	radio = Radio(receiver)
	radio.browsers_available = True
	messages, _ = watch(radio)
	radio.set_output(BROKEN)
	try:
		assert messages[0] == "error: Could not cast to Kitchen (Sonos): no route. Playing in the browser again."
		assert radio.browser_stream is not None
	finally:
		radio.close()


def test_late_lost_cast_leaves_the_new_output_alone(receiver):
	receiver.has_sound_card = False
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.set_output(kitchen(receiver))
	old = radio.caster
	radio.set_output(kitchen(receiver))
	new = radio.caster
	count = len(messages)
	try:
		old.on_lost()
		assert radio.caster is new
		assert new.released is None
		assert radio.browser_stream is None
		assert len(messages) == count
	finally:
		radio.close()


class AudioWatcher(FakeReceiver):
	"""A FakeReceiver that records each change to local_audio."""

	def __init__(self):
		self.audio_changes = []
		super().__init__()
		self.audio_changes.clear()

	@property
	def local_audio(self):
		return self.local

	@local_audio.setter
	def local_audio(self, enabled):
		self.audio_changes.append(enabled)
		self.local = enabled


def test_casting_from_browsers_keeps_the_sound_card_off():
	receiver = AudioWatcher()
	radio = Radio(receiver)
	radio.set_output(BROWSERS)
	radio.set_output(kitchen(receiver))
	try:
		assert radio.browser_stream is None
		assert True not in receiver.audio_changes
	finally:
		radio.close()


def test_failed_cast_from_browsers_plays_in_browsers_again(receiver):
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.set_output(BROWSERS)
	radio.set_output(BROKEN)
	try:
		assert radio.browser_stream is not None
		assert not receiver.local_audio
		assert messages[-1] == "error: Could not cast to Kitchen (Sonos): no route. Playing in the browser again."
	finally:
		radio.close()


def test_failed_cast_says_it_plays_here(receiver):
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.set_output(BROKEN)
	assert radio.browser_stream is None
	assert receiver.local_audio
	assert messages == ["error: Could not cast to Kitchen (Sonos): no route. Playing here again."]


def test_choosing_browsers_again_keeps_the_stream(receiver):
	radio = Radio(receiver)
	radio.set_output(BROWSERS)
	stream = radio.browser_stream
	try:
		radio.set_output(BROWSERS)
		assert radio.browser_stream is stream
		assert stream.running
	finally:
		radio.close()


def test_lost_cast_without_sound_card_or_browsers_plays_nothing(receiver):
	receiver.has_sound_card = False
	radio = Radio(receiver)
	messages, _ = watch(radio)
	radio.set_output(kitchen(receiver))
	radio.caster.on_lost()
	assert radio.caster is None
	assert radio.browser_stream is None
	assert messages[-1] == "Sonos: Kitchen stopped playing the radio. This computer has no sound card, so nothing plays."
