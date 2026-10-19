import sys

from airwaves import sdr

ACCESS = -3
BUSY = -6
TIMEOUT = -7


def test_linux_access_error_names_the_udev_rule(monkeypatch):
	monkeypatch.setattr(sys, "platform", "linux")
	assert "udev" in sdr.dongle_error_text(sdr.LibUSBError(ACCESS))


def test_linux_busy_error_names_the_kernel_module(monkeypatch):
	monkeypatch.setattr(sys, "platform", "linux")
	assert "dvb_usb_rtl28xxu" in sdr.dongle_error_text(sdr.LibUSBError(BUSY))


def test_access_error_elsewhere_names_another_program(monkeypatch):
	monkeypatch.setattr(sys, "platform", "win32")
	assert "Another program" in sdr.dongle_error_text(sdr.LibUSBError(ACCESS))


def test_other_errors_keep_their_text():
	error = sdr.LibUSBError(TIMEOUT, "while opening")
	assert sdr.dongle_error_text(error) == f"Could not open the dongle. {error}"
