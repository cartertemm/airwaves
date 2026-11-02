from datetime import datetime, timezone

from airwaves import flight_log
from airwaves.sdr import AcarsMessage


def message(label, text):
	return AcarsMessage(131.55, "2", ".N123AB", label, "1", text, time=datetime.now(timezone.utc))


def test_a_signed_eta_is_not_a_time():
	assert flight_log.utc_to_local("-123") is None
	assert flight_log.utc_to_local("+123") is None


def test_a_signed_eta_is_left_in_the_text():
	line = flight_log.describe(message("H1", "/ALT350/ETA-123"))
	assert "at 350 ft" in line
	assert "/ETA-123" in line


def test_a_waypoint_time_that_is_not_a_time_is_left_out():
	text = "#M1BPOSN33080W111591,TFD,256000,350,PXR,123000,DRK,M48,"
	line = flight_log.describe(message("H1", text))
	assert "None" not in line
	assert "over TFD," in line
	assert "next PXR at " in line
