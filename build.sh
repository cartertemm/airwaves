#!/bin/bash
# Builds dist/sdr: one file that runs without Python or Homebrew installed.
set -euo pipefail
cd "$(dirname "$0")"

# PyAudio builds against PortAudio during uv sync.
brew install librtlsdr portaudio
uv sync --extra sonos --extra airplay
if [ ! -f src/airwaves/libnrsc5.dylib ]; then
	./build-nrsc5.sh
fi

mkdir -p build
# PyInstaller needs a script, not a module, to start from.
printf 'import sys\nfrom airwaves.sdr import main\nsys.exit(main())\n' > build/sdr_main.py

uv run --with pyinstaller pyinstaller --noconfirm --clean --workpath build/pyinstaller --distpath dist sdr.spec

echo "Built dist/sdr"
