# Start here — the IT9175 dongle (`048d:275a`)

Read this first, then `docs/protocol.md` for the wire and `docs/verification.md`
for what was measured. `README.md` is the public-facing summary.

## What the device is

An ITE **IT9175** ISDB-T demodulator with its tuner behind the OFDM processor,
sold as the **GMA NOW** dongle. USB `048d:275a`, three bulk endpoints
(`0x02` out, `0x81` in, `0x84` TS). 6 MHz ISDB-T raster; the driver scans
473.143–695.143 MHz in 6 MHz steps. Fully in user space: firmware upload,
bring-up, tune and TS are all ordinary bulk transfers.

This is the workspace's most complete driver and the reference implementation —
if a protocol question comes up for another stick, the answer is usually here.

## Bench state (2026-10-23)

- **The dongle is not attached.** `python -m it9175 list` shows only
  `048d:9308` (bus 1 addr 57) and `048d:9309` (bus 1 addr 14). Do not restate
  the 2026-10-19 measurements as fresh ones.
- The only hardware run on record is **2026-10-19, Windows**: WinUSB via Zadig,
  DTA-115 modulator on a closed cable at 599.143 MHz, no antenna. Lock, 19,141
  packets, 0 sync errors, PAT/PMT, H.264 + AAC. Numbers and raw register reads
  are in `docs/verification.md`.
- macOS and Linux have never been executed; same libusb path, expected to work.
- Off-air has never been tested **through this driver**. The Android app runs
  did use an external antenna (2026-10-21, five services decoded).

## Commands

```bash
python -m it9175 list                              # what is on the bus
python -m it9175 sim                               # full path, fake device, no hardware
python -m it9175 probe --freq 599143               # init + tune + status
python -m it9175 play --freq 599143 --out cap.ts   # TS to a file
python -m it9175 scan --start 473143 --stop 695143 --step 6000
python -m unittest discover -s tests               # 21 tests, no hardware
```

`-v` reports failed exchanges and the driver's own notes. `--tuner-type 0|1`
overrides `OFDM 0xEC86`.

## Java parity

`it9175/java` is the Android core. `SelfTest` replays init + two tunes and
compares every write with `src/test/resources/it9175/expected.txt`, which
`tools/gen_java_9175.py` generates from the Python. Both were checked on
2026-10-23: regeneration produced no diff, and the rebuilt test printed
`it9175 java self-test: OK (295 commands)`. To run it, use JDK 17+ (on this
machine `javac` is not on `PATH`; the workspace JDK is
`..\OpenDTVmod\tools\jdk17\bin`, so set `JAVA_HOME` to it):

```powershell
& "$env:JAVA_HOME\bin\javac.exe" -d it9175\java\out (Get-ChildItem it9175\java\src -Recurse -Filter *.java).FullName
& "$env:JAVA_HOME\bin\java.exe" -cp "it9175\java\out;it9175\java\src\test\resources" ph.pbcnx.it9175.SelfTest
```

## Proven — do not re-derive

- Tuner **type 0** for this unit: `0xEC86` reads 1 on cold boot and 0 after the
  init scripts, and the vendor reads it after the scripts. Forcing type 1 gave
  no lock (2026-10-19).
- The demod's **first bulk read starts mid-packet**; `read_ts` locks onto the
  `0x47` phase. Two tests cover it (`tests/test_device.py`).
- Firmware: 9,036 B, 189 chunks, SHA-256 `451b09a4…c3575c`; LINK reports
  `05 05 00 00`, OFDM `05 07 00 00` on the bench unit. The driver only checks
  for a non-zero version, not equality with the image.
- The simulator seeds a **different tuner** (`ed03=3`, `ed23=4642`) than the
  bench unit (`ed03=7`, `ed23≈3705`). That is why the golden tuning words in
  `tests/test_tuner.py` (lo 60,939) differ from the bench words (lo `0xD510`).
  Compare a run's own threshold line, not the table.
- Tune writes `0xFBB9` **twice** (row[5], then row[6]); that is the vendor
  order and the second value is what sticks.
- No start-streaming command exists. Tune leaves the demod running; the host
  reads `0x84`.
- **Android is app-proven**: OpenDTV-MOD (`com.pbcnx.opendtvmod`, whose driver
  this Java core is ported from) played 599.143 MHz live on a Xiaomi
  `22081212UG`, Android 15, on 2026-10-18 — chip `0x9175`, LINK `05 05`, OFDM
  `05 07` — and decoded five services off an external antenna on 2026-10-21.
  `tools/java_math_check.py` against that driver's source re-ran identical on
  2026-10-23. This repo's `it9175/java` has the 295-command parity test, not an
  app build of its own.
- Off-air reception **through this Python driver** is still untested; the cable
  run is the only bench record.

## Traps

- **`firmware.bin` is vendor material.** It is tracked in the private tree and
  `release.ps1` withholds it by pattern. Never `git push public main`; verify
  the computed withhold list before any release.
- **The simulator cannot show what a register becomes.** `SimBackend` returns
  what was written plus a hard-coded `0x47 = 1`. A sim pass says nothing about
  silicon. This bit the 9309 work; do not repeat it here.
- **Run from a checkout.** The vendored pyusb and Windows DLL live in
  `vendor/` and are not in the wheel; an installed copy fails with
  `ModuleNotFoundError: No module named 'usb'` (measured 2026-10-23).
- The public snapshot has **no firmware image**; `sim` and the tests still run
  (placeholder zeros) but `probe`/`play` need the real image.
- Two other sticks on the bus are not this one: `048d:9308` and `048d:9309`.
  Do not bind or tune them from this repo.

## Licence

MIT, deliberately: it matches `it9308`/`it9309`, keeps the Android app's terms
free, and all code here is the project's own port of `ph.opendtv` plus protocol
facts — no GPL source. The vendored pyusb (BSD-3-Clause) and libusb DLL
(LGPL-2.1) are declared in `NOTICE`; the vendor firmware is outside the licence.

## Where the detail is

| file | what |
|---|---|
| `docs/protocol.md` | frame formats, AFA commands, firmware model, tune path, status registers, simulator limits |
| `docs/verification.md` | what was run, when, with which numbers |
| `docs/compatibility.md` | every stick in the workspace, four operating systems |
| `it9175/device.py` | transport, bring-up, TS alignment, `SimBackend` |
| `it9175/tuner.py` | script interpreter, thresholds, tune maths, lock/status |
| `it9175/tables.py`, `firmware.py` | generated data — regenerate with `tools/gen_tables.py`, do not hand-edit |
| `tools/gen_java_9175.py` | regenerates `Tables.java` + `expected.txt` |
| `tools/java_math_check.py` | compares Python maths with the original Java |

## Next moves

1. When the stick is back on the bus: re-run `probe --freq 599143` and record
   the date, version strings, threshold line, tune words and packet count.
2. Antenna test — the closed-cable run never exercised real reception.
3. Linux and macOS runs (expect no code change; `udev/99-it9175.rules` exists).
4. A long run (hours) with `tools/ts_cc.py` on the capture.
