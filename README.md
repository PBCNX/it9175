# it9175 — ITE IT9175 ISDB-T dongle (`048d:275a`)

User-space driver for the ISDB-T dongle sold as **GMA NOW** (USB `048D:275A`,
ITE IT9175 demodulator). It speaks the dongle's own USB protocol, uploads its
firmware from user space, runs the tuner scripts, and streams MPEG-TS to a file,
stdout or UDP. No kernel driver, no vendor library, Python 3 and libusb only.

This is the workspace's most complete driver and its reference implementation:
the wire format, the tables and the tuning maths are documented here in full.

## The device

| | |
|---|---|
| USB ID | `048d:275a` (VID `048d` = ITE) |
| Chip | ITE **IT9175** ISDB-T demodulator, with the tuner behind its OFDM processor |
| Standard | ISDB-T, 6 MHz raster (UHF 473–695 MHz in this driver's scan range) |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN MPEG-TS |
| Tuner type | read from OFDM `0xEC86`; **0** on the unit measured on 2026-10-19 |
| Read size | 16,356 B per TS bulk read = 87 × 188-byte packets |

`docs/protocol.md` has the frame layout, the AFA command set, the firmware
model and the tune path. `docs/compatibility.md` places this stick among the
others on Windows, macOS, Linux and Android.

## What works, and the evidence

Every hardware number below was measured once, on **2026-10-19, Windows**, with
the dongle bound to WinUSB through Zadig and a **DTA-115 modulator driving a
closed cable at 599.143 MHz** — no antenna. The full record, including the
things that went wrong, is in [`docs/verification.md`](docs/verification.md).

| Check | Measured 2026-10-19 |
|---|---|
| Enumeration | `048d:275a bus 1 addr 7` |
| Chip | version 1, id `0x9175` |
| Firmware | 9,036 B / 189 chunks; LINK `05 05`, OFDM `05 07` |
| OFDM wake (`0xEC4C=0xA8`) | alive on the first write; recovery paths never needed |
| Tune words at 599.143 MHz | `lo=0xD510`, `iq=0xD52B` |
| Lock | **yes** — strength 100, quality 50–55, C/N 13 dB, −45 dBm |
| Transport stream | **19,141 packets, 0 sync errors, 0 trailing bytes** |
| Service | PAT program 1 → PMT `0x1000`; PCR/H.264 `0x100`; AAC `0x101`; data ES `0x511–513` |

**This cannot be re-run today.** On 2026-10-23 the dongle is not on the bus:
`python -m it9175 list` shows only `048d:9308` (bus 1 addr 57) and `048d:9309`
(bus 1 addr 14). Treat the table as a record of a measurement, not as a claim
that the driver works on the bench right now.

Not yet proven, and not implied by the above:

- **macOS and Linux** — same libusb code path, never executed there. Windows
  is the only OS with a hardware run.
- **Off-air reception** — the 2026-10-19 run used a modulator on a closed
  cable. No antenna has ever been attached.
- **Long runs** — the recorded run is 8 s of stream; hours of stability and
  USB drop behaviour are untested.
- **The OFDM recovery paths** (`diagnose_ofdm` A/B/C) — written for a silent
  OFDM processor, never needed on this unit, so never exercised.

## Install

### From a checkout (the supported way)

Nothing to install. The tree carries its own pyusb under `vendor/usb`, and a
64-bit `libusb-1.0.dll` under `vendor/windows/x64`, so from the repository root:

```bash
python -m it9175 list
```

`device.py` prepends `vendor/` to `sys.path` and prefers the bundled DLL on
Windows. Python 3.9+ is required; the 2026-10-23 checks ran on CPython 3.14.3.

### `pip install .`

`pyproject.toml` builds the package and an `it9175` console script, but the
wheel carries neither `vendor/usb` nor the Windows DLL. An installed copy
therefore needs pyusb and libusb from the system — measured on 2026-10-23, a
package-only copy fails with `ModuleNotFoundError: No module named 'usb'`.
Use the checkout unless you are packaging it yourself.

### Windows

Bind the dongle to WinUSB with [Zadig](https://zadig.akeo.ie/) before the first
run. The bundled `libusb-1.0.dll` is used automatically; `IT9175_LIBUSB` points
the driver at a different one.

### Linux

```bash
sudo cp udev/99-it9175.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

The rule grants `uaccess` on `048d:275a`; replug afterwards. No kernel driver is
involved, so nothing needs blacklisting.

## Firmware

The image is **9,036 bytes**, SHA-256
`451b09a40d072d3e7c0b805f3d180a8c8e10456a3768cce0cc27510c05c3575c`, sent as
189 chunks and started with the vendor's command sequence. The driver hashes it
before uploading and refuses a different image.

It is vendor material and is **not part of the public distribution**:

- the private tree carries it at `it9175/firmware.bin` and `release.ps1`
  withholds it from the public snapshot;
- in a public clone, supply it with `--firmware PATH` or `IT9175_FIRMWARE`, or
  place it at `it9175/firmware.bin`;
- do not redistribute it. See [`NOTICE`](NOTICE).

The simulator and the test suite do **not** need it: without an image the fake
device uploads 9,036 placeholder zero bytes and says so in its output.

## Run

```bash
python -m it9175 list                      # enumerate 048d devices
python -m it9175 probe --freq 599143       # open, initialise, tune, report
python -m it9175 tune --freq 599143        # tune and print the signal
python -m it9175 play --freq 599143 --out capture.ts
python -m it9175 play --freq 599143 --udp 127.0.0.1:5000
python -m it9175 scan                      # 473.143–695.143 MHz, 6 MHz steps
```

`probe`, `tune`, `play` and `scan` also accept `--sim`, which swaps the USB
backend for the fake device while keeping the rest of the path identical. `-v`
sends every failed exchange and the driver's own notes to stderr. `--tuner-type`
overrides the type read from `0xEC86`; forcing type 1 on the measured unit
produced no lock, which is why the driver uses type 0.

## The simulator

```bash
python -m it9175 sim
```

```
chip version=1 id=0x9175
fw LINK before=00 00 00 00
firmware downloaded (9036 bytes)
fw LINK after=05 05 00 00
...
tune 599143 kHz: programmed in 50 ms, lock=True after 50 ms
lock: True {... 'raw_strength': 72, ...}
ts bytes: 16356 sync: 0x47
firmware: 9036 bytes in 189 chunks, commands=200
```

The millisecond figures vary between runs (50–51 ms observed); everything else
in that output is deterministic.

`SimBackend` (in `it9175/device.py`) is a register-level fake: writes land in a
dict, reads return them, command 34 reports a version once command 35 has
"booted", `0x4C` clears itself after the firmware consumes it, `0x47` reports
lock, and `read_ts` synthesises aligned 188-byte packets. `python -m it9175 sim`
runs the real `It9175Device` and `Tuner` against it and exits non-zero unless
init, tune and a TS read all succeed.

What it is good for: framing, command order, table and tuning-maths regressions,
and the TS alignment logic — the same Python the hardware path runs.

What it cannot show: **a model only returns what was written into it.** No
register in `SimBackend` acquires a value the hardware derives; `0x47` is
`return 1` unconditionally; there is no timing, no RF, no firmware execution
and no USB error behaviour. A sim pass is not evidence about a register, a lock
or the vendor image. Only the bench says whether a chip did it.

`python -m unittest discover -s tests` runs the suite (21 tests: framing, tables,
tuning maths, device, endpoints). In a public clone the firmware-hash test skips
and the rest pass, because the fake device no longer requires the image.

## Java / Android core

`it9175/java` is a dependency-free port of the protocol, firmware upload, tuner
init, tuning and status, for an Android app that supplies the USB transport and
owns the TS reader. See [`java/README.md`](it9175/java/README.md).

Parity with the Python is checked two ways, both re-run on 2026-10-23:

- `tools/gen_java_9175.py` regenerates `Tables.java` and
  `src/test/resources/it9175/expected.txt` **byte-identically** from the Python
  tables and command log (`git status` stays clean);
- `SelfTest` replays init + tune 599143 + tune 473143 against a canned-register
  IO and compares every write with that log:

  ```
  it9175 java self-test: OK (295 commands)
  ```

## Layout

| path | what |
|---|---|
| `it9175/` | the driver package: `afa.py` framing, `device.py` transport + fake backend, `tuner.py` scripts and maths, `tables.py`/`firmware.py` generated data, `cli.py` |
| `docs/protocol.md` | USB protocol, AFA command set, firmware model, tune path |
| `docs/verification.md` | what was tested, when, with which numbers |
| `docs/compatibility.md` | every stick in the workspace, four operating systems |
| `tests/` | 21 unit tests, no hardware required |
| `tools/` | table generators and the Java cross-check |
| `it9175/java/` | Java core and self-test for Android |
| `vendor/` | pyusb (BSD-3-Clause) and the Windows libusb DLL (LGPL-2.1) |
| `udev/` | Linux permission rule |

## Licence

MIT — see [`LICENSE`](LICENSE). Chosen deliberately:

- it matches the workspace's newer trees (`it9308`, `it9309`), so code and
  register facts can move between them without a licensing boundary;
- it is permissive enough for the Android app that consumes the Java core,
  without forcing the app's own terms;
- the Python and Java here are a port of the project's **own** Android driver
  (`ph.opendtv`) and of protocol facts observed on the wire. `s870` and
  `smsrio` are GPL-2.0; only facts and register values ever cross from them,
  never code. The only third-party code is pyusb (BSD-3-Clause) and the Windows
  libusb DLL (LGPL-2.1), both declared in [`NOTICE`](NOTICE).

The vendor firmware image is **not** covered by this licence and is not
distributed — see [`NOTICE`](NOTICE).
