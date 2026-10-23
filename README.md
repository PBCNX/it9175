# it9175 — ITE IT9175 ISDB-T dongle (`048d:275a`)

User-space driver for the ISDB-T dongle sold as **GMA NOW** (ITE IT9175
demodulator). It speaks the dongle's own USB protocol, uploads its firmware,
tunes, and streams MPEG-TS to a file, stdout or UDP. libusb on Windows, macOS
and Linux; a Java core for Android. No kernel driver, no vendor library.

## Device

| | |
|---|---|
| USB ID | `048d:275a` |
| Chip | ITE IT9175 ISDB-T demodulator, 6 MHz raster |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN MPEG-TS |
| TS read | 16,356 B per bulk read = 87 × 188-byte packets |

## Status

| Platform | State |
|---|---|
| **Windows** | ✅ measured 2026-10-19: lock and TS at 599.143 MHz |
| **Linux / macOS** | 🟡 same libusb path, never executed there |
| **Android** | ✅ app path tested 2026-10-18 / 2026-10-21 |

The Windows run used WinUSB (Zadig) with a DTA-115 driving a **closed cable**:
lock, 19,141 packets, 0 sync errors, PAT/PMT, H.264 + AAC. Numbers and raw
registers are in [`docs/verification.md`](docs/verification.md).

**The dongle is not on the bus today (2026-10-23)** — `python -m it9175 list`
shows only the 9308 and 9309 sticks — so the table is a record of a
measurement, not a claim about the bench right now. Off-air reception and
hours-long runs are untested through this driver.

Android was proven by the app this Java core comes from (OpenDTV-MOD): live
599.143 MHz playback on a Xiaomi `22081212UG`, Android 15, on 2026-10-18, and
five services decoded off an external antenna on 2026-10-21.

## Install

From a checkout — the supported way, nothing to install. pyusb 1.3.1 and a
64-bit `libusb-1.0.dll` are vendored:

```bash
python -m it9175 list
```

`pip install .` builds the package and an `it9175` console script, but the wheel
carries neither vendored copy, so an installed package needs pyusb and libusb
from the system (measured 2026-10-23: it fails with `ModuleNotFoundError: No
module named 'usb'`).

- **Windows**: bind the dongle to WinUSB with [Zadig](https://zadig.akeo.ie/).
  `IT9175_LIBUSB` points at a different DLL.
- **Linux**: `sudo cp udev/99-it9175.rules /etc/udev/rules.d/`, reload udev,
  replug. The rule grants `uaccess`; no kernel driver is involved.

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
python -m it9175 probe --freq 599143       # init, tune, report
python -m it9175 play --freq 599143 --out capture.ts
python -m it9175 play --freq 599143 --udp 127.0.0.1:5000
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
reader. See [`it9175/java/README.md`](it9175/java/README.md).

`SelfTest` replays init + two tunes and compares every write with the Python
command log: `it9175 java self-test: OK (295 commands)`. `Tables.java` and that
log regenerate byte-identically with `tools/gen_java_9175.py`.

## More

- [`docs/protocol.md`](docs/protocol.md) — framing, AFA commands, firmware
  model, tune path, status registers, simulator limits
- [`docs/verification.md`](docs/verification.md) — every number and its date
- [`docs/compatibility.md`](docs/compatibility.md) — all sticks, four OSes
- [`START-HERE.md`](START-HERE.md) — bench state, commands, traps

## Licence

MIT — see [`LICENSE`](LICENSE). Same terms as `it9308`/`it9309`; a port of the
project's own `ph.opendtv` driver plus protocol facts, so nothing GPL crosses
in. The vendor firmware is outside the licence (`NOTICE`).
