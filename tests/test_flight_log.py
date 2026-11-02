from datetime import datetime, timezone

import pytest

from airwaves import flight_log
from airwaves.sdr import AcarsMessage

RECEIVED = datetime(2026, 11, 2, 22, 26, tzinfo=timezone.utc)
STAMP = RECEIVED.astimezone().strftime("%H:%M")


def message(label, text, flight="", registration="N123AB", block_id="1"):
	return AcarsMessage(131.55, "2", registration, label, block_id, text, flight=flight, time=RECEIVED)


def at(hhmm):
	return flight_log.utc_to_local(hhmm)


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


@pytest.mark.parametrize("sent, expected", [
	(
		message("16", "222600,36977,0130, 139,N 33.425,W112.010 KLAS/MMGL", flight="Y41747", registration="XA-VLH"),
		f"Flight Y4 1747 (XA-VLH) from LAS (Las Vegas) to GDL (Guadalajara), position report, at 36,977 ft near PHX (Phoenix), heading 139, ETA {at('0130')}",
	),
	(
		message("16", "N 41.481,W122.595,36014,6, 139"),
		"N123AB, position report, at 36,014 ft near ROF (Montague) | 6, 139",
	),
	(
		message("15", "(2N33080W111591 ABC DE350-48(Z"),
		"N123AB, position report, at 35,000 ft near CGZ (Casa Grande), -48 C | ABC DE",
	),
	(
		message("H1", "#M1BPOSN33080W111591,TFD,223000,350,PXR,224500,DRK,M48,1A2B", flight="AA0042"),
		f"Flight AA 42 (N123AB), position report, at 35,000 ft near CGZ (Casa Grande), -48 C, over TFD at {at('2230')}, next PXR at {at('2245')}, then DRK",
	),
	(
		message("H1", "#CFBFLR/FR2611021430  12345606ENGINE FAULT/IDFMC,ADIRU"),
		f"N123AB, fault report at {at('1430')} in cruise: ENGINE FAULT, reported by FMC, ADIRU",
	),
	(
		message("5U", "KPHX KLAX-SA"),
		"N123AB, weather request for PHX (Phoenix), LAX (Los Angeles)",
	),
	(
		message("H1", "OUT0211261430"),
		f"N123AB, message, left the gate at {at('1430')}",
	),
	(
		message("H1", "/DTKLAX,R25L,152,013000,45"),
		f"N123AB to LAX (Los Angeles), message, runway 25L, ETA {at('0130')}, fuel 152, 45 fuel at arrival",
	),
	(
		message("H1", "/ALT35000/MCH780/FOB123/ETA1530", flight="UA0123"),
		f"Flight UA 123 (N123AB), message, at 35,000 ft, Mach 0.780, fuel 123, ETA {at('1530')}",
	),
	(
		message("H1", "POSRPT 123/02 .N123AB", flight="UA0123"),
		"Flight UA 123 (N123AB), position report",
	),
	(
		message("RA", "PLEASE CALL DISPATCH", block_id="A"),
		"Ground to N123AB, message for the crew | PLEASE CALL DISPATCH",
	),
	(
		message("99", "HELLO", registration=""),
		"Aircraft, label 99 message | HELLO",
	),
])
def test_describe(sent, expected):
	assert flight_log.describe(sent) == f"{STAMP}: {expected}"


def test_a_position_far_from_airports_gives_the_distance():
	line = flight_log.describe(message("H1", "N45.000 W40.000"))
	assert line.startswith(f"{STAMP}: N123AB, message, ")
	assert line.endswith(" km from CVU (Corvo)")
