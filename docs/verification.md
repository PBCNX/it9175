# Verification

Three kinds of evidence are kept apart here:

- **machine evidence** — tests, simulator, Java self-test, byte-for-byte table
  regeneration. Reproducible on any machine, re-run on 2026-10-23.
- **bench evidence** — one hardware run on Windows, 2026-10-19. It cannot be
  repeated today: on 2026-10-23 no `048d:275a` is on the bus.
- **app evidence** — two Android runs recorded in the OpenDTV tree
  (2026-10-18, 2026-10-21). They used the app's own IT9175 driver, so they
  prove the protocol on a phone but not this repo's Java core.

## Automated tests — re-run 2026-10-23

```
python -m unittest discover -s tests
Ran 21 tests in 0.457s
OK
```

(The wall time moves between runs; the count and result do not.)

CPython 3.14.3, Windows. None of the 21 needs hardware; one of them reads the
vendor image, so it runs only when `it9175/firmware.bin` is present and skips
otherwise.

| Area | What is asserted |
|---|---|
| `test_afa` | read/write/command frames are byte-identical to the Java framing, checksums round-trip, malformed responses are rejected |
| `test_tables` | six scripts parse, every opcode/proc is valid, band tables have 8 fields per row, the image is 9,036 B in 189 chunks with the documented SHA-256, a missing image is reported |
| `test_tuner` | thresholds and the per-channel PLL/IQ words match the Java implementation at five frequencies; band selection is monotonic |
| `test_device` | simulated init uploads firmware, loads scripts, tunes, reports signal, returns aligned TS and recovers sync after a partial packet; init also works with no vendor image |
| `test_usb` | endpoint discovery/claim works and a missing `0x84` is reported clearly |

### Public tree (vendor image absent) — 2026-10-23

The release snapshot withholds `it9175/firmware.bin`, so the tree was copied
without it and checked there:

```
Ran 21 tests ... OK (skipped=1)
python -m it9175 sim
  ...
firmware: 9036 bytes in 189 chunks, commands=200 (zeros: vendor image not read)
```

Before this change the same tree failed four `test_device` tests and `sim`
raised `FileNotFoundError`; the fake device now uploads the correct number of
placeholder zero bytes and says so. The bytes are never executed, so this says
nothing about the vendor image.

## Simulated end-to-end — 2026-10-23

```
python -m it9175 sim
chip version=1 id=0x9175
fw LINK before=00 00 00 00
firmware downloaded (9036 bytes)
fw LINK after=05 05 00 00
fw OFDM=05 05 00 00
...
tune 599143 kHz: programmed in 50 ms, lock=True after 50 ms
ts bytes: 16356 sync: 0x47
firmware: 9036 bytes in 189 chunks, commands=200
```

The `ms` figures vary between runs (50 ms and 51 ms both observed on
2026-10-23); everything else is deterministic. The omitted lines are the
diagnostic register dump (`regs before/after tuner init`).

What this proves: `It9175Device.init`, `Tuner.init`, `tune`, `wait_lock`,
`status` and `read_ts` run in order against a backend that obeys the framing.
What it does not prove: any register behaviour — `SimBackend` returns what was
written into it, plus a hard-coded `0x47 = 1`. See `docs/protocol.md` §9.

## Cross-check against the Java reference

The private-tree Java harness compiles OpenDTV's `It9175Tuner.java` (plus the
data table and small stubs for the three AndroidX constants) with the bundled
JDK and prints its tuning words. The Python port produces exactly the same
values:

```
freq      nc  nv  fcw    lo     iq(16)
473143     5   8  5678  46638  46674
497143     5   8  5966  46926  46962
599143     7   4  3595  60939  60957
671143     7   4  4027  61371  61389
695143     7   4  4171  61515  61533
```

Re-run 2026-10-23 against
`OpenDTV/windows-driver/it9175/src/ph/opendtv/source/It9175Tuner.java` — the
same file the Android app uses — and the output was identical, so the phone
runs above exercise the same tuning maths this port reproduces. The Java class
differs only in glue: the app's `read`/`write`/`sleep`/`fwVersion` become the
`Io` interface here, and `exec`/`getStatus` are renamed `execOp`/`status`.

The private-tree table generator reproduces the firmware image whose SHA-256
matches the one recorded in the OpenDTV driver notes, which also validates the
array parser.

## Firmware provenance — a second source, 2026-11-02

The 9,036-byte image came from OpenDTV's Java hex and is stored at
`it9175/firmware.bin`. The GMA Now app (`com.gmanmi.digitv` 1.48, versionCode
259) embeds the same image in its driver libraries:

| library | offset | SHA-256 |
|---|---|---|
| `lib/arm64-v8a/libpt275aDrv.so` | 120,160 | `451b09a4…c3575c` |
| `lib/arm64-v8a/libPT917xDrv.so` | 116,064 | `451b09a4…c3575c` |

Method: searched both `.so` for the first 32 bytes of `it9175/firmware.bin`,
took 9,036 bytes at each hit and hashed. Both are byte-identical to
`firmware.bin` (9,036 B, 189 chunks), so no second copy is kept — the identity
is the evidence. Offsets are for that APK version; a rebuild will move them.

The APK is vendor material and is not in the tree. The image is not
redistributable (`NOTICE`); this confirms that the bytes this driver uploads are
the ones a shipping app uses, not only the ones one decompiled Java file
contained. The vendor's exported API surface, and where it exceeds this driver,
is in the private vendor API notes.

## Java port — re-run 2026-10-23

Both directions of the parity check were re-run, not assumed:

1. The private-tree generator regenerated `Tables.java` and
   `src/test/resources/it9175/expected.txt` from the current Python tables and
   command log. `git status` stayed clean: the generated files are identical.
2. The Java sources were recompiled from scratch with JDK 17 and `SelfTest` run
   against the fresh classes:

   ```
   javac -d out (all src/**/*.java)
   java -cp "out;src/test/resources" ph.pbcnx.it9175.SelfTest
   it9175 java self-test: OK (295 commands)
   ```

   295 is the number of writes in the Python log for init + tune 599143 + tune
   473143; the test fails on the first differing byte.

The earlier `.class` files under `it9175/java/out` are ignored by git and are
not what this result was measured on.

## Android app run — app evidence, 2026-10-18 and 2026-10-21

These runs are recorded in the OpenDTV tree, not in this repo. They used the
app's IT9175 driver (`windows-driver/it9175/src/ph/opendtv/source`, the source
`it9175/java` is ported from) on Android's `UsbDeviceConnection`. They are the
only on-device Android evidence, so they are cited here with their scope.

| | 2026-10-18 | 2026-10-21 |
|---|---|---|
| Device | Xiaomi `22081212UG`, Android 15 (SDK 35), USB host | same |
| App | OpenDTV-MOD | `com.pbcnx.opendtvmod` |
| Tuner | `1165:10074` = `048d:275a` in decimal, ITE "GMA NOW dongle" | same |
| Result | **live playback** at 599.143 MHz: chip `0x9175`, LINK `05 05`, OFDM `05 07`, ~30 fps | decoded GMA 479.143, IBC13 491.143, TV5 497.143, NET25 557.143, INCTV 683.143; PTV 473.143 no lock |

Screenshot of the 2026-10-18 run: `refactor/test-artifacts/live-599143.png`
(4.5 MB, 02:58), beside the device-run block in `refactor/BASELINE.md`.

Two caveats, both from reading the source notes:

- That same `BASELINE.md` still has a "Not yet verified" list saying install,
  USB permission and firmware upload are pending. It was written before the
  device-run block and not updated, so the dated block and the screenshot are
  the evidence, not that list.
- These runs exercise the **app's** driver. This repo's `it9175/java` is proven
  against the Python by `SelfTest` (295 commands), not by an app build; see the
  section above.

The 2026-10-21 pass also recorded a tuner-side negative: at 617.143 MHz the
IT9175 read strength 0 / −90 dBm while a Sony `048d:9308` on the same antenna
locked and saw a TS with no PMT. That is a reception difference, not a protocol
one.

## Bench run — Windows, 2026-10-19

Recorded once; not reproducible today. Dongle `048d:275a` bound to WinUSB with
Zadig; DTA-115 (serial 4115002287, port 2) driving a **closed cable** at
599.143 MHz, fed by the pbcnx orchestrator v23 with a recorded ISDB-T capture.
No antenna.

| Check | Result |
|---|---|
| Enumeration | `048d:275a bus 1 addr 7` |
| Chip | version 1, id `0x9175` |
| Firmware | uploaded 9,036 B / 189 chunks; LINK `05 05`, OFDM `05 07` |
| OFDM wake | alive on the first write, recovery paths not needed |
| Tuner | type 0, `ed03=7`, `ed23≈3705` |
| Tune words | `lo=0xD510`, `iq=0xD52B` — match the computed values for the hardware's thresholds |
| Lock | **yes**, strength 100, quality 50–55, C/N 13 dB, −45 dBm |
| TS | 19,141 packets, 0 sync errors, 0 trailing bytes |
| Service | PAT program 1 → PMT `0x1000`, PCR `0x100`, H.264 `0x100`, AAC `0x101`, data ES `0x511–513` |

Note the discrepancy with the simulator's seed: the bench unit reported
`ed03=7` and `ed23≈3705`, the simulator seeds `ed03=3`, `ed23=4642`. That is
why the bench tune words (0xD510 / 0xD52B) are not the golden table's
(60,939 / 60,957). A real run's own threshold line is the thing to compare.

Two findings from the run were fixed or documented:

* The demod's first bulk read starts **mid-packet**; `read_ts` now locks onto
  the `0x47` phase and emits whole 188-byte packets (two regression tests).
* `0xEC86` reads `1` on a cold boot and `0` after the init scripts. The vendor
  code reads it after the scripts, so **type 0** is used; forcing type 1 with
  `--tuner-type 1` produced no lock, confirming type 0 for this unit.

Minor observations: 2 continuity errors on the video PID and 3 on TDT over
8 seconds (source feeding at half its native bitrate), and no antenna test yet.

### Windows re-check at 32,768 — 2026-11-03

Same unit, moved from the Mac, after the TS read size changed to 32,768:

- `preflight` READY, `048d:275a` bus 1 addr 4.
- cold boot (`fw LINK before=00 00 00 00`) → 9,036 B upload → `ff 00 05 05` /
  `ff 00 05 07`; tuner type 0, `ed03=7`, `ed23=3703`; tune locked, strength 100,
  −32 dBm, SNR 12, BER 0.
- 20 s `play` on 479.143: 24,108,744 B, **128,238 packets**, 0 trailing,
  **0 sync errors**, 8 PAT programs, **1 CC error** (`0x0c73`); quality
  72 → 78 → 72.

Full-tune UHF sweep, same script as the Pi: **15/38 locked** — 479143 485143
491143 497143 503143 509143 515143 527143 557143 563143 575143 587143 617143
659143 683143.

That is the Pi's 14 plus `683143` (strength 41 here, 34 there — borderline). The
fourteen shared channels, the PAT programs and the PIDs match across macOS,
Linux and Windows; the only differences are at the weak edge.

## Linux — Raspberry Pi 5, 2026-11-03

Host: Raspberry Pi 5, aarch64, Debian GNU/Linux 13 (trixie), kernel
`6.18.39+rpt-rpi-v8`, Python 3.13.5, pyusb 1.3.1 (vendored), libusb 1.0.28.
Device: `048d:275a`, bcdDevice 2.00, serial `GO04RB99`, bus 1 addr 22.

udev: `udev/99-it9175.rules` installed. The rule now grants `GROUP="plugdev"` as
well as `uaccess`, because a headless SSH session has no logind seat and the
uaccess ACL is never applied — measured: `crw-rw-r-- root root` before the rule,
`crw-rw---- root plugdev` after. Without it, `probe` failed at
`claim interface 0: Access denied`.

Cold start (`fw LINK before=00 00 00 00`): 9,036 B uploaded, then
`fw LINK after=ff 00 05 05`, `fw OFDM=ff 00 05 07`. Tuner type 0, `ed03=7`,
`ed23=3705`, thresholds `[77187 102916 154375 205833 308750 411666 617500
950000]`. The 2026-10-19 Windows unit read `05 05 00 00` / `05 07 00 00`; the
leading bytes differ per unit, and the driver only requires a non-zero reply.

Probe 479.143 MHz: **locked**, strength 100, quality 0, −32 dBm, SNR 12,
BER 0/10000. Quality read 0 at probe time and 72 during the stream.

20 s `play` on the same channel, real antenna:

| | |
|---|---|
| bytes | 23,690,256 |
| packets | **126,012** |
| trailing bytes | 0 |
| sync errors | **0** |
| bitrate | ≈ 9.48 Mbps |
| programs | 8 in PAT (96, 97, 98, 101, 102, 103, 104, 112) |
| streams | H.264 (`0x1b`), AAC (`0x0f`), data (`0x06`/`0x0d`); MPEG-2 audio on program 102 |

Status during the stream: lock stayed true; quality 72 → 67 → 64.

**Caveat — warm re-open is flaky.** A second process started immediately after a
streaming one once failed with `no answer from the LINK processor`; a retry a
few seconds later succeeded, firmware intact (`ff 00 05 05`, no upload) and
locked again. Seen twice, not explained yet; the likely cause is the device still
streaming into an unread `0x84`. A replug recovers. Recorded so the next session
does not read it as a protocol regression.

Also observed: `dwc_otg: ... trimming xfer length` in dmesg during the stream —
this run used the old 16,356-byte read, which is not a multiple of 512. macOS
later showed the same size as OVERFLOW followed by a stalled pipe; the default
is now 32,768 (see the macOS section).

This makes Linux ✅ with the aarch64 qualifier; x86_64 Linux was not measured.

### Re-check at 32,768 — 2026-11-03

Same Pi and unit, after the TS read size changed:

- the first probe after the move was cold (`ec86=1`, `ed23=0`), uploaded, locked;
- 20 s `play` on 479.143: 24,043,320 B, **127,890 packets**, 0 trailing,
  **0 sync errors**, the same 8 PAT programs; quality 66 → 73 → 67;
- **CC errors fell to 12** total, from ≈800 on the 16,356-byte run of the same
  mux. The read size was causing linux packet loss too, not just the macOS
  overflow.

The warm re-open flake **recurred**: a `scan` started right after the `play`
process failed with `no answer from the LINK processor`; after a 10 s pause the
same command ran. The `dispose_resources()` cleanup did not cure it.

### UHF sweep — full tune, 2026-11-03

One process, 473.143–695.143 MHz in 6 MHz steps, full `wait_lock` per channel:
**14/38 locked** — 479143 485143 491143 497143 503143 509143 515143 527143
557143 563143 575143 587143 617143 659143.

- Strong and repeatable: 479, 485, 497 (strength 100), 509 (97), 491/503/527
  (93), 515 (90), 557 (79).
- Borderline (strength 34–72) and **variable between runs**: 563, 575, 617,
  659; 485 and 683 also flip. Treat a single no-lock as weak evidence.
- The quick `scan` command gave 13/38 and missed 485143, which locks on a full
  tune. Quick mode is one attempt; it under-reports.
- `status` BER read **4898 on every channel**, including no-signal ones — the
  BER register looks stale during a sweep. Do not use it to judge a channel.

## macOS — Intel, 2026-11-03

Host: MacBook Pro, x86_64, Python 3.13.2, libusb 1.0.30. Device `048d:275a`,
serial `GO04RB99`, 480 Mb/s on the USB 3.1 bus.

- Enumerate: ok — `0x02`/`0x81`/`0x84`/`0x85`.
- Cold boot: `fw LINK before=00 00 00 00` → 9,036 B upload → `ff 00 05 05` /
  `ff 00 05 07`.
- Tuner type 0, `ed03=7`, `ed23=3705`; tune took 1,7–1,8 s; **lock true**,
  quality 92 on the first tune (later tune-time reads said 0).

**First attempt failed, and found a real driver bug.** A 16,356-byte read
returned 0 at 500 ms and **OVERFLOW** at 2,000 ms; a 16,384-byte read then
returned **EPIPE** (stalled pipe), and every later read stayed EPIPE. The device
sends more than 16,356 bytes, and 16,356 is not a multiple of 512. macOS rejects
the overrun and halts the endpoint; Linux had only logged `trimming xfer length`
for the same mismatch. The 20 s play before the fix wrote 188 bytes.

Fix (`b84e493`): default TS read **32,768** (a 512-byte multiple), clear the halt
on open, and retry once on EPIPE/OVERFLOW. With that size the endpoint delivers:
404 reads, 13,183,504 B in 10 s, 0 errors.

Final 20 s `play` on 479.143 MHz (the 32,768 default applied at runtime; the same
code path, committed default identical):

| | |
|---|---|
| bytes | 22,866,064 |
| packets | **121,628** |
| trailing bytes | 0 |
| sync errors | **0** |
| bitrate | ≈ 9.15 Mbps |
| programs | 8 in PAT — the same set as the Pi run |
| streams | H.264 (`0x1b`), AAC (`0x0f`), data (`0x06`/`0x0d`) |

Status during the stream: lock true, quality 73 → 79 → 85.

Continuity errors: ≈230 across PIDs, and **the Pi capture on the same mux has
more** (`0x01cf`: 277 vs 24), so this is feed/reader packet loss, not a macOS
property. Both runs report 0 sync errors and the same PAT/PMTs.

macOS **Intel x86_64 ✅**. Apple Silicon is untested. A clean rerun after pulling
`b84e493` is owed (this run used the runtime override).

## Android demo app — our Java core, 2026-11-03

Xiaomi `22081212UG` (`ditingp`), Android 15, our demo APK (42,448 B, minSdk 23 /
target 34) installed over ADB; the same dongle (`GO04RB99`) via OTG. Android's
resolver listed `it9175 demo` next to the vendor app and OpenDTV-MOD; chosen
**Just once**, so no default handler was changed.

- bring-up: `chip version=1 id=0x9175 firmware=ff 00 05 05` (warm, no upload),
  `init=true`, `tune=479143 lock=true`.
- capture (20 s, pulled snapshot): **202,884 packets**, 38,142,192 B, 0 trailing,
  **8 PAT programs** — the same PAT/PIDs as the other hosts; `ts_check` reports
  117 sync errors and ≈120 CC errors (≈0.06%).
- **The first run was wrong, and the phone found it.** Writing each 188-byte
  packet straight to an unbuffered `FileOutputStream` (193,489 packets) produced
  ≈10,030 CC errors (5.2%): the writer was starving the USB reader. A 64 KiB
  `BufferedOutputStream` cut that to ≈120 (≈0.06%); the residual sync/CC errors
  are a USB/OTG artefact to investigate. The 9308 solved this class of problem
  with queued `UsbRequest`s — that is the next step here if the residual matters.
- This proves the Java core plus `AndroidTransport`/`AndroidTsReader` inside an
  app built from this repo. OpenDTV-MOD still runs its own driver (above).

## External use — BMLPLAYER (reported, not re-measured)

The BMLPLAYER session runs this driver as a subprocess (`play --out -`,
receive only) and reported these off-air runs on **Windows 11 x64**, Python
3.14, WinUSB, real antenna:

- 2026-11-01, 479.143 MHz, 180 s: lock true, strength 100, quality 84 at 60 s
  and 73 at 120 s; 422,996 packets at 60 s, 845,468 at 120 s; 225 MB file.
  PAT/PMT read and captions decoded (81 statements); video/audio not played.
- 2026-11-01, 497.143 MHz, 180 s: quality 97/100; 217,937 packets at 60 s,
  436,481 at 120 s; 116 MB.
- 2026-10-31, in-player scan: 8 channels; TV5 5.48 Mbit/s quality 97, GMA
  10.6 Mbit/s quality 76; 15 s per mux on 479/485/497/503/515 MHz.

Sync errors were not counted and the captures were deleted, so this
corroborates the driver's off-air use on Windows; it is not a bench row.

## Not verified

1. macOS Apple Silicon — the Intel x86_64 run is the only macOS measurement.
2. x86_64 Linux — only the aarch64 Pi 5 was measured.
3. Long-run stability (hours) and USB drop behaviour under load.
4. The OFDM recovery path (A/B/C) — not needed on either measured unit.
5. The warm re-open failure in the Linux section — reproduced again after the
   `dispose_resources()` cleanup; still not explained.
6. The Android USB reader under sustained load — the demo shows ≈0.06% sync/CC
   errors on a phone; a queued `UsbRequest` pipeline (as the 9308 uses) is not
   implemented here.

Suggested first run on a new machine:

```bash
python -m it9175 list
python -m it9175 probe --freq 599143
python -m it9175 play --freq 599143 --seconds 30 --out first.ts
python tools/ts_check.py first.ts
```

If `probe` fails, run with `-v`; stderr shows every failed exchange and the
driver's own bring-up notes (firmware version, OFDM wake-up, tuner type,
thresholds).
