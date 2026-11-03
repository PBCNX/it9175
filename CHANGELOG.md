# Changelog

Notable changes only. The version in `pyproject.toml` and
`it9175/__init__.py` and the `vX.Y.Z` tag are kept in step; see
[`docs/versioning.md`](docs/versioning.md).

## 0.2.0 — 2026-11-03

- Android: a minimal demo APK (`it9175/java/android/demo`) links the Java core
  and the USB adapter by source, tunes 479.143 MHz and writes an aligned TS
  file. Builds 2026-11-03 (`it9175-demo-debug.apk`, 42 KB, no firmware inside).
- Android demo **ran** 2026-11-03 on a Xiaomi 22081212UG (Android 15), dongle via
  OTG: 202,884 packets, 8 PAT programs, ≈0.06% CC after buffering. The first
  unbuffered version lost ≈5.2% continuity — one write per 188-byte packet
  starved the reader; fixed with a 64 KiB `BufferedOutputStream`.
- Windows re-check at 32,768-byte reads (2026-11-03): off-air 479.143, 20 s =
  128,238 packets, 0 sync errors, 1 CC error. Full UHF sweep 15/38 lock — the
  same fourteen channels as the Pi plus borderline 683143.
- Linux re-check at 32,768-byte reads (2026-11-03): 127,890 packets, 0 sync
  errors, CC errors down from ≈800 to 12 on the same mux. Full UHF sweep 14/38
  lock; the quick `scan` under-reports (one attempt). The warm re-open flake
  remains.
- macOS **Intel x86_64 verified** 2026-11-03: cold upload, tune, lock and 20 s
  of TS — 121,628 packets, 0 sync errors, the same 8 PAT programs as the Pi.
  Apple Silicon untested.
- USB: TS reads are now **32,768 bytes** (a 512-byte multiple), with a cleared
  halt and one retry on EPIPE/OVERFLOW. macOS reported the old 16,356-byte read
  as OVERFLOW and then a stalled pipe; Linux had only logged `trimming xfer`.
- Linux **verified** on a Raspberry Pi 5 (aarch64), 2026-11-03: cold boot
  (firmware blank → 9,036 B upload), lock at 479.143 MHz, 20 s = 126,012
  packets, 0 sync errors, 8 programs. The udev rule now also grants
  `GROUP="plugdev"`, because `uaccess` never applies to a headless SSH login.
- Java: `TsReader` seam for the `0x84` endpoint, and an Android adapter
  (`AndroidTransport`, `AndroidTsReader`, `device_filter.xml`). Compile-checked
  against `android-34` on 2026-11-03; the demo above ran it on a phone.
- docs: `docs/vendor-api.md` — the vendor driver's exported API, the name match
  with `tuner.py`, and the features this driver does not expose.
- docs: firmware provenance from the GMA Now 1.48 APK (same 9,036-byte image,
  both driver libraries).
- docs: `docs/testing.md` run sheet and `tools/preflight.py`.
- tools: follow the workspace rename `OpenDTVmod` → `OpenDTV`; both defaults
  worked before the move and neither did after it.
- gitignore: `it9306/` is a separate repo, like `it9308/` and `it9309/`.
- Provenance marker `it9175-pbcnx` in `--version`, `It9175Device.PROVENANCE`
  and NOTICE — attribution only, no telemetry.
- Cleanup: the Java firmware upload now checks every result, `UsbBackend.close()`
  disposes the pyusb handle, and the device-name table is shared.
- Public mirror: 72 files; withholds `START-HERE.md`, `release.ps1`,
  `vendor/windows/` and the reverse-engineering tools.

## 0.1.1 — 2026-10-23

- README simplified (221 → 115 lines); no code change.
- Android evidence recorded: OpenDTV-MOD on a Xiaomi `22081212UG`, live at
  599.143 MHz on 2026-10-18 and five services decoded on 2026-10-21.

## 0.1.0 — 2026-10-23

- First public snapshot: README, MIT licence, NOTICE, `START-HERE.md`,
  `docs/{protocol,verification,compatibility}.md`, 21 tests, Java core with the
  295-command `SelfTest`.
- `it9175/firmware.bin` withheld from the public tree.
