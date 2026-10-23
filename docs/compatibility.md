# Stick compatibility, all sticks, four operating systems

Snapshot: 2026-10-21. Scope: every stick this workspace has touched, and whether
it works — or can work — on Windows, macOS, Linux and Android.

Why the answer differs per stick: **every driver here is user space over libusb**,
so OS support reduces to one question — *can this chip be started from user
space?* For most of these sticks the firmware upload is an ordinary vendor
request, so Windows, macOS, Linux and Android behave the same. The S870 is the
exception, and it is documented separately in `s870/docs/boot-rom.md`.

Legend: ✅ proven on hardware · 🟡 expected, same userspace path, untested ·
⛔ no path · ⏸ parked, not implemented.

## Matrix

| stick | USB ID | Windows | macOS | Linux | Android |
|---|---|---|---|---|---|
| **IT9175** (GMA NOW dongle) | `048D:275A` | ✅ | 🟡 | 🟡 | ✅ |
| **IT9308** (Sony) | `048D:9308` | ✅ | 🟡 | 🟡 | ✅ vendor path |
| **IT9309** | `048D:9309` | ⏸ | ⏸ | ⏸ | ⏸ |
| **Siano Rio** (S270 / generic) | `187F:0600` | ✅ | 🟡 | 🟡 | ✅ |
| **S870** (DiBcom STK8096GP) | `10B8:1FA0` | ⛔ | ⛔ | 🟡 handoff ✅, tune open | ⛔ |
| **TBS5580** | `734C:5580` | ⏸ | ⏸ | ⏸ (kernel driver only) | ⏸ |

The GMA NOW dongle is **not** a separate stick: it is the IT9175, `048D:275A`
(`PID_IT9175` in `it9175/device.py`). Older notes that say "GMA NOW: none bound"
mean only that Linux has no kernel driver for it, not that the device is
unsupported — the userspace driver handles it.

## Per stick

### IT9175 / GMA NOW dongle — `048D:275A`

- ✅ **Windows** — Python driver with the tuner port, TS validated from this
  machine.
- 🟡 **macOS / Linux** — plain libusb, no OS driver involved; the same code
  should run unchanged.
- ✅ **Android** — the app path is proven on hardware: `OpenDTV-MOD`
  (`com.pbcnx.opendtvmod`) played live 599.143 MHz on a Xiaomi `22081212UG`,
  Android 15, on 2026-10-18 — chip `0x9175`, LINK `05 05`, OFDM `05 07`,
  ~30 fps — and decoded GMA, IBC13, TV5, NET25 and INCTV on 2026-10-21. This
  repo's `it9175/java` is ported from that driver and passes the 295-command
  parity test, but has not itself been packaged in an app.

### IT9308 (Sony) — `048D:9308`

- ✅ **Windows** — Python driver plus the captured bring-up sequence
  (`sequence.bin`), TS validated.
- 🟡 **macOS / Linux** — same libusb path.
- ✅ **Android** — vendor path; Java API is `bringUp(image)`, `tune(kHz)`,
  `setStreaming(on)`.

### IT9309 — `048D:9309`

- ⏸ **All four** — the sample's demod answers at neither Sony (`0x64/0x66`) nor
  Panasonic (`0x70/0x73`) addresses. Parked and documented in
  `it9308/docs/9309.md`.

### Siano Rio — `187F:0600` (S270 and the unbranded stick)

- ✅ **Windows** — live TS: 33,280 packets in 10 s, 0 sync errors, 5.0 Mbps,
  PAT/PMT with H.264 plus audio.
- 🟡 **Linux** — highest-confidence 🟡 here: nothing in this path needs a kernel
  driver, the upload is ordinary vendor requests. Just not run yet.
- 🟡 **macOS** — same libusb path.
- ✅ **Android** — lock at 599.143 MHz, video and audio confirmed on the phone.

### S870 (DiBcom STK8096GP) — `10B8:1FA0`

- ⛔ **Windows** — only the vendor `mod7700.sys` (MyGica package) can boot the
  ROM. It then owns the interface, and handing the device to WinUSB/libusbK
  rebinds it, which clears the firmware. No path for this driver.
- ⛔ **macOS** — no `dib0700` in the OS, and user space cannot make the ROM jump.
- 🟡 **Linux** — the one real path, in two stages:
  - ✅ cold start by the in-kernel `dvb_usb_dib0700` (the only loader that works;
    user space was proven unable with libusb, raw `USBDEVFS_BULK` and a 2 ms
    fast path — see `s870/docs/boot-rom.md`);
  - ✅ warm handoff: after `rmmod` the firmware keeps running (our driver reads
    `0x10200`) and the demod answers I2C (`0x40 reg 0x0380 -> 0x01b3`);
  - ⏳ **open: the tune.** Bring-up is captured, a successful tune is not, so
    `ENABLE_VIDEO` yields an empty pipe. Route: replay the tuning sequence from
    the `s870c.pcap` run that produced the validated 31 MB `s870.ts`, or port
    the `dib8000`/`dib0090` `set_params`.
- ⛔ **Android** — needs a kernel driver the phone does not have (checked on a
  Xiaomi 12T Pro: no `DVB` symbol in its kernel config at all).

### TBS5580 — `734C:5580`

- ⏸ **All four** — no userspace port exists. Linux works through the in-kernel
  driver. A phased spike is scoped: upload `dvb-usb-id5580.fw`, prove the
  `0x90/0x91` I2C tunnel, then read the Si2183 chip ID at `0x67` before any
  demod work.

## What moves the 🟡 cells to ✅

| action | sticks | cost |
|---|---|---|
| Run the existing Python driver on the Pi (no code change expected) | Siano, IT9175, IT9308 | minutes, one replug each |
| Finish the S870 tune (replay from `s870c.pcap`) | S870 on Linux | one session, no new hardware |
| Real Mac hardware | every macOS cell | not possible on this machine |

## Rule of thumb

- **Siano, IT9175, IT9308** — userspace drivers; OS support is essentially free,
  the only question is whether someone has run them there yet.
- **S870** — its boot ROM only accepts a firmware load from kernel context.
  Treat it as a Linux/TV-box stick, not a phone stick.
- **IT9309, TBS5580** — parked for concrete, documented reasons: no demod
  response, and no port written.
