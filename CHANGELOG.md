# Changelog

## 0.3.0 — 2026-11-24

- Package renamed to `com.pbcnx.drivers.it9175`; the Android door contract is `com.pbcnx.tuner` 2.0.0.
- `it9175/java`: a dependency-free Java core, the contract, and a demo activity that lists, tunes and plays.
- Android: one session owner for open/close/reopen, a queued reader, and recovery that rebuilds a wedged stick.
- Reader: the driver counts its own TS packets, null packets and resyncs, and logs them every 5 s.
- Recovery: the cold bring-up is measured, and `recover` reports how the chip came back.
- TMCC: partial reception and the three layers are decoded; the zero trap is closed by the canonical segment rule.
- IIP/EWBS: the IIP is decoded and its CRC-32 checked; the EWBS activation bit is read where the part exposes it.
- CLI: a machine without libusb or without a dongle now gets one line and exit 2, not a traceback.
- Firmware is verified for size and SHA-256 before use, and is never distributed in this repository.

## 0.2.1 — 2026-11-21

- Recovery on macOS and Linux, and a supervisor that survives a replug.

## 0.2.0 — 2026-11-19

- TMCC decoding, the IIP decoder, and the first Windows/Linux measurements.

## 0.1.1, 0.1.0 — 2026-11

- First working protocol: firmware upload, tune, lock, MPEG-TS read.
