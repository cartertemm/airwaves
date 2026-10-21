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


def started_gain(monkeypatch, *args):
	"""Runs sdr with args and returns the gain it opens the dongle with."""
	opened = {}

	def receiver(device_index, freq_mhz, region, gain):
		opened["gain"] = gain
		raise sdr.LibUSBError(-3)

	monkeypatch.setattr(sdr, "list_devices", lambda: [sdr.Device(0, "Generic RTL2832U", "00000001")])
	monkeypatch.setattr(sdr, "Receiver", receiver)
	assert run(monkeypatch, *args) == 1
	return opened["gain"]


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
