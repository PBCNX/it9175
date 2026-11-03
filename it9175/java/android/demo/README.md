# it9175 Android demo

A minimal harness, not a product: it links the **it9175 Java core** and the
**Android USB adapter** by source, opens the dongle, uploads firmware, inits,
tunes 479.143 MHz, and writes an aligned MPEG-TS file. The only reason it exists
is to prove *this* core on a phone; OpenDTV-MOD is the real app.

## Build

Needs JDK 17 and the Android SDK (platform 34, build-tools 34/35).

```bash
cd it9175/java/android/demo
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk
gradle assembleDebug --offline       # drop --offline if the AGP cache is cold
```

APK: `build/outputs/apk/debug/it9175-demo-debug.apk` (gitignored).

On Windows, with `JAVA_HOME` and `ANDROID_HOME` already pointing at a JDK 17 and
the SDK:

```powershell
gradle assembleDebug --offline
```

## Firmware

The vendor image is **not** in this repo or in the APK. Push it to the app's
external files directory, which needs no storage permission:

```bash
adb install -r build/outputs/apk/debug/it9175-demo-debug.apk
adb shell mkdir -p /sdcard/Android/data/ph.pbcnx.it9175.demo/files
adb push /path/to/private/tree/it9175/firmware.bin \
    /sdcard/Android/data/ph.pbcnx.it9175.demo/files/firmware.bin
```

The app refuses to start without a 9,036-byte image and says so on screen.

## Run

1. Plug the `048d:275a` dongle into the phone (USB host / OTG).
2. Launch **it9175 demo**, grant the USB permission prompt.
3. The status screen shows the bring-up line (`chip version=1 id=0x9175 …`),
   `init=`, `tune=479143 lock=`, the output path and a packet counter.
4. `Stop` closes the reader and the USB handle.

Pull and check the capture:

```bash
adb pull /sdcard/Android/data/ph.pbcnx.it9175.demo/files/it9175-demo.ts
python tools/ts_check.py it9175-demo.ts
```

Expected on a live mux: `0 sync errors`, PAT/PMT, H.264 + AAC.

Measured 2026-11-03 on a Xiaomi `22081212UG` (Android 15), dongle via OTG:
**202,884 packets**, 8 PAT programs, ≈0.06% sync/CC errors. The first version
wrote each 188-byte packet to an unbuffered stream and lost ≈5.2% continuity —
the write was starving the USB reader. The output stream is now 64 KiB buffered.

## What it does and does not prove

- Proves the Java core (`It9175Device`/`Tuner`/`AfaIo`) and
  `AndroidTransport`/`AndroidTsReader` run inside an Android app.
- Does **not** implement a player, a channel list, EPG or remote control; it
  tunes one fixed frequency.
- Alignment lives in the app (`TsAligner`), matching the Python
  `It9175Device._align_ts`; the core stays raw.
- The reader is blocking (32,768-byte reads); the queued `UsbRequest` path was
  deliberately not added until a phone shows it is needed.

## Licence

MIT, same as the repo. No vendor code; no vendor binary in the APK or the tree.
