import importlib

# Loaded on first use, so the directory tools do not load numpy and the dongle driver.
RECEIVER_API = {"list_devices", "Receiver", "detect_region", "AM", "SW", "FM", "AIR", "NOAA", "ACARS", "ACARS_EU", "HdUnavailable", "AcarsMessage", "Alert"}


def __getattr__(name):
	if name in RECEIVER_API:
		return getattr(importlib.import_module(".sdr", __name__), name)
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
