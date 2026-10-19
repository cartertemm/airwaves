# PyInstaller spec for dist\sdr.exe and dist/sdr. Run it through build.bat or build.sh.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# sdr and nrsc5 load their libraries by path, and the casting modules are
# only imported when casting, so PyInstaller cannot find them alone.
if sys.platform == "darwin":
	sys.path.insert(0, os.path.join(SPECPATH, "src"))
	from airwaves.libraries import NRSC5_LIBRARY, RTLSDR_LIBRARIES, library_path
	# At the top level, under the name libnrsc5 links to, so the driver PyInstaller
	# collects for libnrsc5 and the one sdr loads are a single file.
	binaries = [(library_path(name), ".") for name in (*RTLSDR_LIBRARIES, NRSC5_LIBRARY)]
else:
	dlls = ("libnrsc5.dll", "rtlsdr.dll")
	binaries = [(os.path.join(SPECPATH, "src", "airwaves", name), "airwaves") for name in dlls]
# airportsdata reads its airport list from its own folder.
datas = collect_data_files("airportsdata")
hiddenimports = collect_submodules("pyatv") + collect_submodules("soco")
hiddenimports += ["airwaves.sonos_cast", "airwaves.airplay_cast"]

a = Analysis(
	[os.path.join(SPECPATH, "build", "sdr_main.py")],
	pathex=[os.path.join(SPECPATH, "src")],
	binaries=binaries,
	datas=datas,
	hiddenimports=hiddenimports,
)

# PyInstaller copies DLLs from folders such as numpy.libs to the top level too,
# but the packages load them from their own folder, so drop the top-level copy.
packaged = {os.path.basename(name) for name, _, _ in a.binaries if os.path.dirname(name).endswith(".libs")}
a.binaries = [entry for entry in a.binaries if os.path.dirname(entry[0]) or entry[0] not in packaged]

exe = EXE(
	PYZ(a.pure),
	a.scripts,
	a.binaries,
	a.datas,
	name="sdr",
	console=True,
)
