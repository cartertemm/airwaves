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

uv run --with pyinstaller pyinstaller --noconfirm --clean --workpath build\pyinstaller --distpath dist sdr.spec || exit /b 1

echo Built dist\sdr.exe
