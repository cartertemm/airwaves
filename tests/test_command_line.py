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
