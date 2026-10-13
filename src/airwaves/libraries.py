"""Finds the native libraries that sdr loads on macOS."""
import os
import sys

RTLSDR_DYLIB = "librtlsdr.0.dylib"
NRSC5_DYLIB = "libnrsc5.dylib"
# The app built by build.sh unpacks its libraries to sys._MEIPASS. From source, build-nrsc5.sh puts libnrsc5 in this folder.
BUNDLE_FOLDER = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
# Homebrew on Apple silicon, then Homebrew on Intel.
LIBRARY_FOLDERS = (BUNDLE_FOLDER, "/opt/homebrew/lib", "/usr/local/lib")


def library_path(name, folders=LIBRARY_FOLDERS):
	"""Returns the first copy of the library called name in folders. Without one it returns name, so the system searches where it normally does."""
	for folder in folders:
		path = os.path.join(folder, name)
		if os.path.exists(path):
			return path
	return name
