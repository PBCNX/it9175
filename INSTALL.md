# Install — all platforms

User-space driver for the **IT9175** ISDB-T dongle (`048d:275a`, sold as
GMA NOW). Source checkout plus vendor firmware; no installer, no service, no
GUI.

| platform | state |
|---|---|
| Windows 10/11 x64 | tested |
| Linux x86_64 / Raspberry Pi 5 | tested |
| macOS Intel x86_64 | tested 2026-11-03; Apple Silicon untested |
| Android | library + demo app; ran on Android 15, 2026-11-03 |

## Common

- **Python 3.9+**, 64-bit. Tested with 3.13.
- **pyusb is vendored** under `vendor/usb`; running from the checkout needs no
  `pip install`.
- **Firmware** `it9175/firmware.bin` (9,036 B) is required and is **not** in the
  public snapshot. The private checkout carries it, or pass `--firmware PATH` /
  set `IT9175_FIRMWARE`.
- Run commands from the checkout root.
- The driver talks to the dongle over USB only; no network, no telemetry.

```bash
python -m it9175 list
python -m it9175 probe --freq 479143
python -m it9175 play --freq 479143 --seconds 20 --out capture.ts
python -m it9175 play --freq 479143 --seconds 20 --out capture.ts --status-interval 5
python -m it9175 scan
```

On Windows use `py -3` instead of `python`.

## Windows

1. Install **64-bit Python 3.9+**. Check: `py -3 --version`.
2. Plug in the dongle. Run `py -3 -m it9175 list`.
3. If it is not listed, bind it to **WinUSB** with
   [Zadig](https://zadig.akeo.ie/): Options → List All Devices → `048d:275a` →
   WinUSB → Install Driver, then replug. Do this once.
4. Firmware: put `firmware.bin` in `it9175/`, or use `--firmware`.
5. The private checkout includes `vendor/windows/x64/libusb-1.0.dll`. If your
   copy does not (public snapshot), install libusb and point to it:

   ```powershell
   $env:IT9175_LIBUSB = "$env:USERPROFILE\libusb\libusb-1.0.dll"
   ```

6. Run:

   ```powershell
   py -3 -m it9175 probe --freq 479143
   py -3 -m it9175 play --freq 479143 --seconds 20 --out capture.ts
   ```

## Linux

Debian/Ubuntu/Raspberry Pi OS:

```bash
sudo apt install libusb-1.0-0
sudo cp udev/99-it9175.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

The rule grants `uaccess` and group `plugdev`. `uaccess` only applies to a
logged-in seat, so over SSH add yourself to the group and log in again:

```bash
sudo usermod -aG plugdev "$USER"
```

Replug the dongle, then:

```bash
python3 -m it9175 list
python3 -m it9175 probe --freq 479143
python3 -m it9175 play --freq 479143 --seconds 20 --out capture.ts
```

No kernel driver is used. The udev rule grants the user access; without it the
claim fails with `Access denied`. Tested on a Raspberry Pi 5 (aarch64).

## macOS

1. Install libusb:

   ```bash
   brew install libusb
   brew --prefix libusb
   ```

2. Use a Python whose architecture matches libusb:
   - Apple Silicon: arm64 Python + `/opt/homebrew/...`
   - Intel: x86_64 Python + `/usr/local/...`

   Check: `uname -m` and `python3 -c 'import platform; print(platform.machine())'`.

3. If pyusb cannot find libusb:

   ```bash
   export IT9175_LIBUSB="$(brew --prefix libusb)/lib/libusb-1.0.dylib"
   ```

4. No udev is needed. Run:

   ```bash
   python3 -m it9175 list
   python3 -m it9175 probe --freq 479143
   python3 -m it9175 play --freq 479143 --seconds 20 --out capture.ts
   ```

macOS **Intel x86_64 is confirmed** (2026-11-03, Intel MacBook Pro, Python
3.13.2, libusb 1.0.30). Apple Silicon is still untested.

## Android

There is no prebuilt APK. Apps integrate the Java core in `java/` and the
Android transport in `java/android/`; `java/android/demo/` is a minimal app that
builds and ran on a Xiaomi `22081212UG` (Android 15): 202,884 packets, 8 PAT
programs.

- JDK 17+, Android SDK/API 34;
- USB host + `device_filter.xml` for `048d:275a`;
- firmware supplied from app storage, not the repo (the demo reads it from its
  external files directory).

## Firmware

- 9,036 bytes, SHA-256
  `451b09a40d072d3e7c0b805f3d180a8c8e10456a3768cce0cc27510c05c3575c`.
- A cold dongle reports `fw LINK before=00 00 00 00`; `probe` and `play` upload
  it, after which LINK reads `ff 00 05 05`.
- Default: `it9175/firmware.bin` in the checkout. Explicit: `--firmware PATH`
  or `IT9175_FIRMWARE`.
- Vendor material: do not redistribute; not in the public snapshot.

## Verify

```text
list   -> 048d:275a ... IT9175 (supported)
probe  -> firmware uploaded, tuner type, lock True, strength/quality
play   -> capture.ts grows, 0 sync errors, PAT/PMT present
```

Signal status at tune time can read quality 0 and rise during the stream; that
is normal. A quick `scan` makes one lock attempt per channel and under-reports —
a no-lock result is weak evidence.

## Troubleshooting

| symptom | cause |
|---|---|
| empty `list` | Windows: WinUSB not bound (Zadig); Linux: udev rule not loaded or user not in `plugdev`; macOS: wrong Python/libusb architecture |
| `Access denied` on claim | udev rule missing, or SSH session without `plugdev` |
| libusb not found | set `IT9175_LIBUSB` (Windows/macOS) |
| firmware 0, upload fails | missing/wrong `firmware.bin`; check path and SHA-256 |
| no lock/TS | wrong frequency, no antenna, or an empty mux |
| `no answer from the LINK processor` right after a stream | known warm-reopen flake: retry after a few seconds, or replug |
| one packet only, then nothing (old macOS/Windows builds) | the pre-0.2.0 16,356-byte TS read overflowed some hosts; use 0.2.0+ |
| status meter looks frozen/zero | `.status()` is a snapshot; quality often reads 0 at tune and rises during the stream |

## Licence

Driver code is MIT (`LICENSE`). The vendor firmware is outside the licence
(`NOTICE`); libusb and pyusb keep their own licences under `vendor/`.
