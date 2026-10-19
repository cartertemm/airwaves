#!/bin/bash
# Builds libnrsc5 for HD Radio and puts it in src/airwaves, where sdr looks first.
# On Linux, set RTLSDR_PREFIX to build against the RTL-SDR driver installed there instead of the distribution's.
set -euo pipefail
cd "$(dirname "$0")"

# The commit that src/airwaves/nrsc5.py is copied from. Change both together.
NRSC5_COMMIT=9beb2c77171472c707f285f51a1385ac4c4a8be6
SOURCE=build/nrsc5
CMAKE_OPTIONS=()

if [ "$(uname)" = "Darwin" ]; then
	brew install cmake autoconf automake libtool pkgconf librtlsdr fftw
	LIBRARY=libnrsc5.dylib
else
	PACKAGES=(git build-essential cmake autoconf automake libtool pkg-config libfftw3-dev libusb-1.0-0-dev)
	if [ -n "${RTLSDR_PREFIX:-}" ]; then
		CMAKE_OPTIONS+=("-DCMAKE_PREFIX_PATH=$RTLSDR_PREFIX")
	else
		PACKAGES+=(librtlsdr-dev)
	fi
	SUDO=$([ "$(id -u)" -eq 0 ] || echo sudo)
	$SUDO apt-get update
	$SUDO apt-get install -y "${PACKAGES[@]}"
	LIBRARY=libnrsc5.so
fi

if [ ! -d "$SOURCE" ]; then
	git clone https://github.com/theori-io/nrsc5.git "$SOURCE"
fi
git -C "$SOURCE" fetch origin
git -C "$SOURCE" checkout "$NRSC5_COMMIT"

# The command line program needs libao, and sdr only uses the library.
cmake -S "$SOURCE" -B "$SOURCE/build" -DBUILD_CLI=OFF ${CMAKE_OPTIONS[@]+"${CMAKE_OPTIONS[@]}"}
cmake --build "$SOURCE/build"
cp "$SOURCE/build/src/$LIBRARY" src/airwaves/

echo "Built src/airwaves/$LIBRARY"
