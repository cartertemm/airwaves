"""Finds the native libraries that sdr loads on macOS and Linux."""
import ctypes
import os
import sys

# The app built by build.sh unpacks its libraries to sys._MEIPASS. From source, build-nrsc5.sh puts libnrsc5 in this folder.
BUNDLE_FOLDER = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
if sys.platform == "darwin":
	RTLSDR_LIBRARIES = ("librtlsdr.0.dylib",)
	NRSC5_LIBRARY = "libnrsc5.dylib"
	# Homebrew on Apple silicon, then Homebrew on Intel.
	LIBRARY_FOLDERS = (BUNDLE_FOLDER, "/opt/homebrew/lib", "/usr/local/lib")
else:
	# Distros name the osmocom driver librtlsdr.so.2 (Ubuntu 24.04) or librtlsdr.so.0 (Debian, older Ubuntu).
	RTLSDR_LIBRARIES = ("librtlsdr.so.2", "librtlsdr.so.0")
	NRSC5_LIBRARY = "libnrsc5.so"
	LIBRARY_FOLDERS = (BUNDLE_FOLDER,)


def library_path(name, folders=LIBRARY_FOLDERS):
	"""Returns the first copy of the library called name in folders. Without one it returns name, so the system searches where it normally does."""
	for folder in folders:
		path = os.path.join(folder, name)
		if os.path.exists(path):
			return path
	return name


def load_library(names, folders=LIBRARY_FOLDERS):
	"""Loads the first of names that loads, looking in folders first. Returns None if none of them load."""
	for name in names:
		try:
			return ctypes.CDLL(library_path(name, folders))
		except OSError:
			pass
	return None
