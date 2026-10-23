import sys

import pytest

from airwaves import sdr


def run(monkeypatch, *args):
	monkeypatch.setattr(sys, "argv", ["sdr", *args])
	return sdr.main()


def test_password_needs_web(monkeypatch):
	with pytest.raises(SystemExit) as stop:
		run(monkeypatch, "--web-password", "secret")
	assert stop.value.code == 2


def test_web_needs_a_speaker_name(monkeypatch):
	with pytest.raises(SystemExit) as stop:
		run(monkeypatch, "--web", "--sonos")
	assert stop.value.code == 2


def test_device_number_must_exist(monkeypatch, capsys):
	monkeypatch.setattr(sdr, "list_devices", lambda: [sdr.Device(0, "Generic RTL2832U", "00000001")])
	assert run(monkeypatch, "--device", "2") == 1
	assert "1: Generic RTL2832U (serial 00000001)" in capsys.readouterr().out


def test_web_with_two_dongles_needs_device(monkeypatch, capsys):
	pytest.importorskip("aiohttp")
	devices = [sdr.Device(0, "Generic RTL2832U", "00000001"), sdr.Device(1, "Generic RTL2832U", "00000002")]
	monkeypatch.setattr(sdr, "list_devices", lambda: devices)
	assert run(monkeypatch, "--web") == 1
	assert "--device" in capsys.readouterr().out


@pytest.mark.parametrize("args", [("--web", "0"), ("--web", "70000"), ("--web", "http"), ("--web", "--web-password", "")])
def test_bad_web_options_are_refused(monkeypatch, args):
	with pytest.raises(SystemExit) as stop:
		run(monkeypatch, *args)
	assert stop.value.code == 2


def opened_with(monkeypatch, *args):
	"""Runs sdr with args and returns the gain and ppm it opens the dongle with."""
	opened = {}

	def receiver(device_index, freq_mhz, region, gain, ppm):
		opened.update(gain=gain, ppm=ppm)
		raise sdr.LibUSBError(-3)

	monkeypatch.setattr(sdr, "list_devices", lambda: [sdr.Device(0, "Generic RTL2832U", "00000001")])
	monkeypatch.setattr(sdr, "Receiver", receiver)
	assert run(monkeypatch, *args) == 1
	return opened


def opened_frequency(monkeypatch, *args):
	opened = {}

	def receiver(device_index, freq_mhz, region, gain, ppm):
		opened["freq"] = freq_mhz
		raise sdr.LibUSBError(-3)

	monkeypatch.setattr(sdr, "list_devices", lambda: [sdr.Device(0, "Generic RTL2832U", "00000001")])
	monkeypatch.setattr(sdr, "Receiver", receiver)
	assert run(monkeypatch, *args) == 1
	return opened["freq"]


@pytest.mark.parametrize("option", ["--web", "--sonos", "--airplay"])
def test_frequency_after_an_option_is_the_frequency(monkeypatch, option):
	if option == "--web":
		pytest.importorskip("aiohttp")
	assert opened_frequency(monkeypatch, option, "97.9") == 97.9


def parsed(*args):
	return sdr.parse_args(sdr.make_parser(), list(args))


@pytest.mark.parametrize(("args", "frequency", "web", "sonos", "airplay"), [
	(("--web", "97.9"), 97.9, sdr.DEFAULT_WEB_PORT, None, None),
	(("--web", "8080"), sdr.FM.min_mhz, 8080, None, None),
	(("--sonos", "97.9"), 97.9, None, "", None),
	(("--airplay", "162.55"), 162.55, None, None, ""),
	(("--sonos", "Mr. Kitchen"), sdr.FM.min_mhz, None, "Mr. Kitchen", None),
	(("97.9", "--sonos", "Kitchen"), 97.9, None, "Kitchen", None),
])
def test_options_and_frequency_in_any_order(args, frequency, web, sonos, airplay):
	result = parsed(*args)
	assert (result.frequency, result.web, result.sonos, result.airplay) == (frequency, web, sonos, airplay)


def test_frequency_given_twice_is_refused():
	with pytest.raises(SystemExit) as stop:
		parsed("98.1", "--web", "97.9")
	assert stop.value.code == 2


def started_gain(monkeypatch, *args):
	return opened_with(monkeypatch, *args)["gain"]


def started_ppm(monkeypatch, *args):
	return opened_with(monkeypatch, *args)["ppm"]


def test_gain_is_auto_by_default(monkeypatch):
	assert started_gain(monkeypatch) == sdr.AUTO_GAIN


def test_gain_comes_from_the_config_file(monkeypatch, tmp_path):
	(tmp_path / "airwaves.conf").write_text("[airwaves]\ngain = 28.0\n")
	assert started_gain(monkeypatch) == 28.0


def test_gain_option_overrides_the_config_file(monkeypatch, tmp_path):
	(tmp_path / "airwaves.conf").write_text("[airwaves]\ngain = 28.0\n")
	assert started_gain(monkeypatch, "--gain", "0") == 0
	assert started_gain(monkeypatch, "--gain", "auto") == sdr.AUTO_GAIN


def test_invalid_gain_in_the_config_file_is_auto(monkeypatch, tmp_path):
	(tmp_path / "airwaves.conf").write_text("[airwaves]\ngain = loud\n")
	assert started_gain(monkeypatch) == sdr.AUTO_GAIN


@pytest.mark.parametrize("gain", ["loud", "-1", "51", "nan"])
def test_bad_gain_is_refused(monkeypatch, gain):
	with pytest.raises(SystemExit) as stop:
		run(monkeypatch, "--gain", gain)
	assert stop.value.code == 2


def test_ppm_is_0_by_default(monkeypatch):
	assert started_ppm(monkeypatch) == 0


def test_ppm_comes_from_the_config_file(monkeypatch, tmp_path):
	(tmp_path / "airwaves.conf").write_text("[airwaves]\nppm = -42\n")
	assert started_ppm(monkeypatch) == -42


def test_ppm_option_overrides_the_config_file(monkeypatch, tmp_path):
	(tmp_path / "airwaves.conf").write_text("[airwaves]\nppm = -42\n")
	assert started_ppm(monkeypatch, "--ppm", "0") == 0


def test_invalid_ppm_in_the_config_file_is_0(monkeypatch, tmp_path):
	(tmp_path / "airwaves.conf").write_text("[airwaves]\nppm = 1000\n")
	assert started_ppm(monkeypatch) == 0


@pytest.mark.parametrize("ppm", ["fast", "1.5", "201", "-201"])
def test_bad_ppm_is_refused(monkeypatch, ppm):
	with pytest.raises(SystemExit) as stop:
		run(monkeypatch, "--ppm", ppm)
	assert stop.value.code == 2
