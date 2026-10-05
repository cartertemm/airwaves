@echo off
cd /d "%~dp0"
uv sync --extra sonos --extra airplay || exit /b 1
if not exist build mkdir build
> build\sdr_entry.py echo from airwaves.sdr import main
>> build\sdr_entry.py echo main()
uv run --with pyinstaller pyinstaller --noconfirm --onefile --console --name sdr --collect-submodules airwaves --collect-all pyrtlsdrlib --collect-all pyatv --distpath dist --workpath build\pyinstaller --specpath build build\sdr_entry.py || exit /b 1
echo Built dist\sdr.exe
