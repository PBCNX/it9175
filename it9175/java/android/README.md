# Android transport for the IT9175 Java core

`AndroidTransport` implements `Transport` over `UsbDeviceConnection`;
`AndroidTsReader` reads endpoint `0x84` and implements `TsReader`. The shape is
the one the 9308 adapter uses, with the 9175's read size and no request queue.

| | |
|---|---|
| interface | 0, claimed with `claimInterface(intf, true)` |
| command OUT / IN | `0x02` / `0x81`, bulk, 500 ms, exact length |
| TS IN | `0x84`, 32,768 B (512-byte multiple; align on 188) |
| endpoints | selected by address |

## Use

1. Add `android/src/main/java/ph/pbcnx/it9175/android/` and
   `android/src/main/res/xml/device_filter.xml` to the app.
2. Declare USB host and the device filter on the activity.
3. Request permission, then open:

```java
AndroidTransport transport = AndroidTransport.open(usbManager, device);
It9175Device tuner = new It9175Device(transport);
tuner.bringUp(firmwareBytes);      // 9,036 B vendor image
tuner.init();
tuner.tune(599143);
tuner.waitLock(false);
AndroidTsReader reader = new AndroidTsReader(transport,
        (data, length) -> demux.write(data, 0, length));
reader.start();
```

4. On pause/detach: `reader.stop(); transport.close();`.

## Ordering

Bring-up, `init()`, `tune()` and `waitLock()` all happen **before**
`reader.start()`. A tune resets the TS endpoint; before a retune:

```java
reader.stop();
tuner.tune(khz);
tuner.waitLock(false);
reader.start();
```

Status settles a few hundred milliseconds after `tune()`; immediately after it,
`status().locked` can still be false.

## Limits

- Blocking reads only. The 9308 uses ten queued `UsbRequest`s because its bridge
  can stall a late consumer; the 9175 reads a 512-byte multiple at a time on
  every host, so the queue is not added until a phone shows it is needed. That
  is the handover's "measure first" rule.
- The first read after a tune may start mid-packet. This reader does not align;
  the app locks onto the `0x47` phase. The Python reference is
  `It9175Device._align_ts`.
- `Listener.onData` gets a **reused** buffer; copy or consume before returning.
- A 500 ms transfer returning 0 is "no lock yet", not an error.
- The reader does not own the device lifecycle: `stop()` before `close()`.

## Firmware

Vendor 9,036-byte image, not in the public repo; supply it from app assets or
private storage. SHA-256:
`451b09a40d072d3e7c0b805f3d180a8c8e10456a3768cce0cc27510c05c3575c`.

## Compile

The adapter lives outside `../src` on purpose: the plain-JVM `SelfTest` must not
need `android.jar`. Compile the core and the adapter together against the SDK:

```bash
cd java/android
javac -source 8 -target 8 \
  -cp "$ANDROID_HOME/platforms/android-34/android.jar" \
  -d out $(find ../src/main/java src/main/java -name '*.java')
```

On Windows with a JDK 17 and android-34 (set `JAVA_HOME` and `ANDROID_HOME`):

```powershell
$jdk = Join-Path $env:JAVA_HOME 'bin\javac.exe'
$android = Join-Path $env:ANDROID_HOME 'platforms\android-34\android.jar'
& $jdk -source 8 -target 8 -Xlint:-options -cp $android -d out `
  (Get-ChildItem ..\src\main\java, src\main\java -Recurse -Filter *.java).FullName
```

Measured 2026-11-03: exit 0. This proves the adapter compiles; it is not a
device run. A phone smoke test is still owed.

## Licence

MIT, same as the repo. Written against the Android USB API; no vendor code
copied.
