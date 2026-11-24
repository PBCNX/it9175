# it9175 — ITE IT9175 ISDB-T dongle (`048d:275a`)

User-space driver for the ISDB-T dongle sold as **GMA NOW** (ITE IT9175). It speaks the dongle's own USB protocol,
uploads its firmware, tunes, and streams MPEG-TS to a file, stdout or UDP; it also reads the multiplex's transmission
parameters (TMCC) and the IIP. Python over libusb (pyusb is vendored, so there is nothing to install); a
dependency-free Java core for Android lives in `it9175/java`.

**Our own code, no vendor code.**

## Device

| | |
|---|---|
| USB ID | `048d:275a` |
| Chip | ITE IT9175 ISDB-T demodulator, 6 MHz raster |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN MPEG-TS |
| Status | strength, quality, SNR, in-band dBm, BER and lock, from the demod's own registers |
| TMCC | mode, guard interval, partial reception, layers A/B/C (modulation, code rate, interleave, segments) |
| IIP | PID `0x1FF0`, one TSP per frame, CRC-32 checked |

## Platforms

Windows, Linux, macOS (Intel and Apple Silicon) and Android. All four are measured on hardware. No kernel driver is involved: libusb over WinUSB on Windows, udev on Linux, libusb on
macOS.

## Install

From a checkout — pyusb is vendored, so no `pip install` is needed.

```bash
python -m it9175 --version      # it9175 0.3.0 (it9175-pbcnx)
python -m it9175 list           # finds the 048d devices present
python -m it9175 sim            # the whole protocol against a simulated device, no hardware needed
```

- **Windows**: bind the dongle to WinUSB with [Zadig](https://zadig.akeo.ie/) and replug it, then get
  `libusb-1.0.dll` from <https://libusb.info> and set `IT9175_LIBUSB` to its full path (or copy it next to
  `python.exe`). Zadig is the device binding; libusb is the library the driver loads.
- **Linux**: `sudo cp udev/99-it9175.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger`,
  then replug. The rule grants `uaccess` plus group `plugdev` (needed over SSH, where there is no logind seat).
- **macOS**: install libusb (`brew install libusb`); on Apple Silicon use an arm64 Python and libusb.

**Firmware.** The image is not in this repository — it is vendor material. Supply your own with `--firmware PATH` or
`IT9175_FIRMWARE`; it is checked for size and SHA-256 before use. `--version`, `list` and `sim` work without it;
anything that opens the stick needs it.

## Use

```bash
python -m it9175 list
python -m it9175 tune  --freq 497143
python -m it9175 tmcc  --freq 497143
python -m it9175 play  --freq 497143 --seconds 30 --out capture.ts
```

Android / JVM:

```java
Tuner tuner = provider.open(context, device, firmware, listener);
tuner.open();
tuner.tune(497143);
tuner.start();
```

`it9175/java/android/demo` is a working activity that lists, tunes and plays.

## License

MIT — see `LICENSE`. `NOTICE` lists what is not ours.
