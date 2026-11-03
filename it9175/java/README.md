# it9175 — Java core (Android)

Pure-JVM implementation of the IT9175 protocol: framing, firmware upload, tuner
init, tuning and status. No Android dependency; the app supplies a `Transport`
for the command endpoint and a `TsReader` for the stream endpoint.

## API

```java
It9175Device device = new It9175Device(transport);
String info = device.bringUp(firmwareImage);   // chip id + firmware version
boolean ok  = device.init();                   // register scripts
boolean hit = device.tune(599143);             // frequency in kHz
boolean lock = device.waitLock(false);         // poll for lock
Status s    = device.status();                 // locked, strength, quality, dBm, BER
int n       = tsReader.read(buffer, 500);      // one TS batch, -1 on timeout
```

`Transport` is the command endpoint only; `TsReader` is the stream endpoint
(`0x84`). The core does not align TS packets — the first batch can start
mid-packet — so the consumer locks onto the `0x47` phase; the Python
`It9175Device._align_ts` is the reference.

## Android adapter

`android/` carries `AndroidTransport` (`UsbDeviceConnection`) and
`AndroidTsReader` (blocking 32,768-byte reads). It lives outside `src/` so the
plain-JVM `SelfTest` needs no `android.jar`. See `android/README.md` for the
open → bring-up → init → tune → start order and the compile command.

`android/demo/` is a minimal harness APK that links the core and the adapter by
source, tunes 479.143 MHz and writes an aligned TS file. It builds on 2026-11-03
(`it9175-demo-debug.apk`, 42 KB, no firmware inside) and ran on a Xiaomi
`22081212UG`, Android 15: 202,884 packets, 8 PAT programs. Build and run
instructions are in `android/demo/README.md`.

## Test

```bash
javac -d out $(find src -name '*.java')
java -cp "out:src/test/resources" ph.pbcnx.it9175.SelfTest
```

On Windows (PowerShell, JDK 17+; set `JAVA_HOME` to your JDK if `javac` is not
on `PATH`):

```powershell
& "$env:JAVA_HOME\bin\javac.exe" -d out (Get-ChildItem src -Recurse -Filter *.java).FullName
& "$env:JAVA_HOME\bin\java.exe" -cp "out;src/test/resources" ph.pbcnx.it9175.SelfTest
```

Expected: `it9175 java self-test: OK (295 commands)`. The test compiles against
Java 8 (`build.gradle`) but any newer JDK runs it.

The private-tree generator regenerates `Tables.java` and
`src/test/resources/it9175/expected.txt` from the Python tuner; the test replays
init + tune 599143 + tune 473143 against a canned-register IO and compares every
write with the Python command list.
