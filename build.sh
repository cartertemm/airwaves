#!/bin/bash
# Builds dist/sdr on macOS or Linux: one file that runs without Python, Homebrew, or the distribution's packages installed.
set -euo pipefail
cd "$(dirname "$0")"

# The osmocom driver version that the Windows build uses too.
RTLSDR_TAG=v2.0.2
RTLSDR_SOURCE=build/rtl-sdr
RTLSDR_PREFIX="$PWD/build/rtlsdr-prefix"

if [ "$(uname)" = "Darwin" ]; then
	# PyAudio builds against PortAudio during uv sync.
	brew install librtlsdr portaudio
	uv sync --extra sonos --extra airplay
	if [ ! -f src/airwaves/libnrsc5.dylib ]; then
		./build-nrsc5.sh
	fi
else
	SUDO=$([ "$(id -u)" -eq 0 ] || echo sudo)
	$SUDO apt-get update
	$SUDO apt-get install -y git build-essential cmake pkg-config libusb-1.0-0-dev portaudio19-dev
	if [ ! -d "$RTLSDR_SOURCE" ]; then
		git clone https://gitea.osmocom.org/sdr/rtl-sdr.git "$RTLSDR_SOURCE"
	fi
	git -C "$RTLSDR_SOURCE" fetch --tags origin
	git -C "$RTLSDR_SOURCE" checkout "$RTLSDR_TAG"
	# The driver then takes the dongle from the dvb_usb_rtl28xxu TV module itself.
	cmake -S "$RTLSDR_SOURCE" -B "$RTLSDR_SOURCE/build" -DDETACH_KERNEL_DRIVER=ON -DCMAKE_INSTALL_PREFIX="$RTLSDR_PREFIX" -DCMAKE_INSTALL_LIBDIR=lib
	cmake --build "$RTLSDR_SOURCE/build"
	cmake --install "$RTLSDR_SOURCE/build"
	uv sync --extra sonos --extra airplay
	# Always rebuild, so libnrsc5 links to this driver and not to the distribution's.
	RTLSDR_PREFIX="$RTLSDR_PREFIX" ./build-nrsc5.sh
fi

mkdir -p build
# PyInstaller needs a script, not a module, to start from.
printf 'import sys\nfrom airwaves.sdr import main\nsys.exit(main())\n' > build/sdr_main.py

uv run --with pyinstaller pyinstaller --noconfirm --clean --workpath build/pyinstaller --distpath dist sdr.spec

echo "Built dist/sdr"
