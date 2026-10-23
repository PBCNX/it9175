# Verification

Two kinds of evidence are kept apart here:

- **machine evidence** — tests, simulator, Java self-test, byte-for-byte table
  regeneration. Reproducible on any machine, re-run on 2026-10-23.
- **bench evidence** — one hardware run, 2026-10-19. It cannot be repeated
  today: on 2026-10-23 no `048d:275a` is on the bus.

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

`tools/java_math_check.py` compiles OpenDTV's `It9175Tuner.java` (plus the data
table and small stubs for the three AndroidX constants) with the bundled JDK
and prints its tuning words. The Python port produces exactly the same values:

```
freq      nc  nv  fcw    lo     iq(16)
473143     5   8  5678  46638  46674
497143     5   8  5966  46926  46962
599143     7   4  3595  60939  60957
671143     7   4  4027  61371  61389
695143     7   4  4171  61515  61533
```

`tools/gen_tables.py` reproduces the firmware image whose SHA-256 matches the
one recorded in the OpenDTV driver notes, which also validates the array parser.

## Java port — re-run 2026-10-23

Both directions of the parity check were re-run, not assumed:

1. `python tools/gen_java_9175.py` regenerated `Tables.java` and
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

## Not verified

1. Off-air reception with an antenna (the run above used the cable).
2. Long-run stability (hours) and USB drop behaviour under load.
3. macOS and Linux runtime — the same libusb path, but not executed there.
4. The OFDM recovery path (A/B/C) — not needed on this unit.
5. Anything on the bench today: the dongle is not attached. `python -m it9175
   list` on 2026-10-23 showed only `048d:9308` (bus 1 addr 57) and `048d:9309`
   (bus 1 addr 14).

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
