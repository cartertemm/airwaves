@echo off
rem Builds dist\sdr.exe: one file that runs without Python installed.
setlocal
cd /d "%~dp0"

uv sync --extra sonos --extra airplay || exit /b 1

if not exist build mkdir build
rem PyInstaller needs a script, not a module, to start from.
echo import sys> build\sdr_main.py
echo from airwaves.sdr import main>> build\sdr_main.py
echo sys.exit(main())>> build\sdr_main.py

rem pyrtlsdrlib loads the dongle driver DLL from its own folder, and the casting
rem modules are only imported when casting, so PyInstaller cannot find them alone.
uv run --with pyinstaller pyinstaller --noconfirm --clean --onefile --console --name sdr ^
	--paths src ^
	--specpath build --workpath build\pyinstaller --distpath dist ^
	--collect-all pyrtlsdrlib ^
	--collect-submodules pyatv ^
	--collect-submodules soco ^
	--hidden-import airwaves.sonos_cast ^
	--hidden-import airwaves.airplay_cast ^
	build\sdr_main.py || exit /b 1

echo Built dist\sdr.exe
