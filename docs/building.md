# Running from source and building

These steps are for running `airwaves` from this folder, or building the app yourself. First set up the dongle as the README describes, then install the libraries for your system below, then follow Installing in the README.

## Windows

Windows needs nothing more than the WinUSB driver from the README.

## macOS

macOS needs no USB driver for the dongle. Install the library that talks to the dongle, and PortAudio for sound, with [Homebrew](https://brew.sh):

```
brew install librtlsdr portaudio
```

HD Radio needs libnrsc5, which Homebrew does not have. To build it, run:

```
./build-nrsc5.sh
```

It installs what the build needs with Homebrew and puts `libnrsc5.dylib` in `src/airwaves`. Without it, everything except HD Radio works.

## Linux

The `rtl-sdr` package from the README also installs the dongle driver that `airwaves` uses when you run it from this folder.

PyAudio builds against PortAudio during `uv sync`, so install it and a compiler:

```
sudo apt install portaudio19-dev build-essential
```

HD Radio needs libnrsc5. On Debian or Ubuntu, run:

```
./build-nrsc5.sh
```

It installs what the build needs with `apt` and puts `libnrsc5.so` in `src/airwaves`. Without it, everything except HD Radio works.

## Building a Windows executable

To give the receiver to someone who does not have Python, run `build.bat`. It builds `dist\airwaves.exe`, one file that includes Python, the packages, and the dongle driver, with Sonos and AirPlay casting and the web frontend:

```
build.bat
```

The other commands are not in the executable.

## Building a macOS or Linux executable

On an Apple silicon Mac with Homebrew, or on Debian or Ubuntu, run `build.sh`. It builds `dist/airwaves`, one file that includes Python, the packages, the dongle driver, and libnrsc5, with Sonos and AirPlay casting and the web frontend. On Linux it builds the dongle driver from source, and the file runs on distributions as old as the one it was built on:

```
./build.sh
```
