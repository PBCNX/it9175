# it9175 — ITE IT9175 ISDB-T dongle (`048d:275a`)

User-space driver for the ISDB-T dongle sold as **GMA NOW** (ITE IT9175
demodulator). It speaks the dongle's own USB protocol, uploads its firmware,
tunes, and streams MPEG-TS to a file, stdout or UDP. libusb on Windows, macOS
and Linux; a Java core for Android. No kernel driver, no vendor library.

Platform setup: [`INSTALL.md`](INSTALL.md).

## Device

| | |
|---|---|
| USB ID | `048d:275a` |
| Chip | ITE IT9175 ISDB-T demodulator, 6 MHz raster |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN MPEG-TS |
| TS read | 32,768 B per bulk read (512-byte multiple; packets are aligned on 188) |

## Status

| Platform | State |
|---|---|
| **Windows** | ✅ closed-cable; off-air: 128,238 packets, 0 sync errors at 32,768-byte reads |
| **Linux** | ✅ Raspberry Pi 5 (aarch64): 127,890 packets, 0 sync errors at 32,768-byte reads; 14/38 UHF channels lock on a full sweep |
| **macOS** | ✅ Intel x86_64 measured 2026-11-03: cold upload, tune, lock, 121,628 packets, 0 sync errors; Apple Silicon untested |
| **Android** | ✅ vendor app 2026-10-18/21; our Java demo ran 2026-11-03 on Android 15 (202,884 packets) |

`✅` measured on hardware · `🟡` code exists, not run on that platform.

## Firmware

9,036 bytes, SHA-256
`451b09a40d072d3e7c0b805f3d180a8c8e10456a3768cce0cc27510c05c3575c`, sent as
189 chunks. The driver hashes it and refuses a different image.

It is vendor material and is **not in this distribution**: the private tree
carries it at `it9175/firmware.bin` and the release withholds it. Supply it with
`--firmware PATH` or `IT9175_FIRMWARE`; do not redistribute it (see
[`NOTICE`](NOTICE)). The simulator and tests run without it, uploading
placeholder zeros.

## Run

```bash
python -m it9175 list
python -m it9175 probe --freq 479143       # init, tune, report
python -m it9175 play --freq 479143 --out capture.ts
python -m it9175 play --freq 479143 --udp 127.0.0.1:5000
python -m it9175 scan                      # 473.143–695.143 MHz, 6 MHz steps
```

`probe`, `tune`, `play` and `scan` accept `--sim` (fake device, same code path);
`-v` sends failed exchanges and driver notes to stderr.

## Simulator and tests

```bash
python -m it9175 sim                       # init, tune and TS against SimBackend
python -m unittest discover -s tests       # 21 tests, no hardware
```

`SimBackend` returns registers that were written into it and a hard-coded
`0x47 = 1`; it proves ordering and arithmetic, never what silicon becomes. A
sim pass says nothing about a lock or the vendor image.

## Java / Android

`it9175/java` is a dependency-free port of the protocol, firmware upload, tuner
init, tuning and status; the app supplies the USB transport and owns the TS
reader. See [`it9175/java/README.md`](it9175/java/README.md). The `android/`
tree next to it carries the USB adapter (`AndroidTransport`, `AndroidTsReader`,
`device_filter.xml`) and a minimal demo app that builds into a ≈42 KB APK and
ran on a Xiaomi `22081212UG`, Android 15 (202,884 packets, 8 PAT programs).

`SelfTest` replays init + two tunes and compares every write with the Python
command log: `it9175 java self-test: OK (295 commands)`. `Tables.java` and that
log regenerate byte-identically from the Python tables; the generator is kept in
the private tree.

## More

- [`INSTALL.md`](INSTALL.md) — Windows, Linux, macOS and Android setup
- [`docs/protocol.md`](docs/protocol.md) — framing, AFA commands, firmware
  model, tune path, status registers, simulator limits
- [`docs/verification.md`](docs/verification.md) — every number and its date
- [`CHANGELOG.md`](CHANGELOG.md) — what changed, and when

## Licence

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 The IT9175 Open Driver Authors. Same terms as `it9308`/`it9309`. The Java core
is a port of OpenDTV's `It9175Tuner` (`jpdcs/OpenDTV`, MIT); the Python driver,
the protocol document and the verification record are this project's. Nothing
GPL crosses in. The vendor firmware is outside the licence (`NOTICE`).
