# PyInstaller spec for dist\sdr.exe. Run it through build.bat.
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# pyrtlsdrlib and nrsc5 load their DLLs from their own folder, and the casting
# modules are only imported when casting, so PyInstaller cannot find them alone.
datas, binaries, hiddenimports = collect_all("pyrtlsdrlib")
# airportsdata reads its airport list from its own folder.
datas += collect_data_files("airportsdata")
binaries += [(os.path.join(SPECPATH, "src", "airwaves", "libnrsc5.dll"), "airwaves")]
hiddenimports += collect_submodules("pyatv") + collect_submodules("soco")
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
