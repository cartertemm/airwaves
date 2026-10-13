#!/bin/bash
# Builds libnrsc5.dylib for HD Radio and puts it in src/airwaves, where sdr looks first.
set -euo pipefail
cd "$(dirname "$0")"

# The commit that src/airwaves/nrsc5.py is copied from. Change both together.
NRSC5_COMMIT=9beb2c77171472c707f285f51a1385ac4c4a8be6
SOURCE=build/nrsc5

brew install cmake autoconf automake libtool pkgconf librtlsdr fftw

if [ ! -d "$SOURCE" ]; then
	git clone https://github.com/theori-io/nrsc5.git "$SOURCE"
fi
git -C "$SOURCE" fetch origin
git -C "$SOURCE" checkout "$NRSC5_COMMIT"

# The command line program needs libao, and sdr only uses the library.
cmake -S "$SOURCE" -B "$SOURCE/build" -DBUILD_CLI=OFF
cmake --build "$SOURCE/build"
cp "$SOURCE/build/src/libnrsc5.dylib" src/airwaves/

echo "Built src/airwaves/libnrsc5.dylib"
