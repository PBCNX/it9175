# it9175 — Java core (Android)

Pure-JVM implementation of the IT9175 protocol: framing, firmware upload, tuner
init, tuning and status. No Android dependency; the app supplies a `Transport`
for the command endpoint and owns the TS reader.

## API

```java
It9175Device device = new It9175Device(transport);
String info = device.bringUp(firmwareImage);   // chip id + firmware version
boolean ok  = device.init();                   // register scripts
boolean hit = device.tune(599143);             // frequency in kHz
boolean lock = device.waitLock(false);         // poll for lock
Status s    = device.status();                 // locked, strength, quality, dBm, BER
```

`Transport` remains the command endpoint only; TS is read by the app from the
stream endpoint.

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

`tools/gen_java_9175.py` regenerates `Tables.java` and
`src/test/resources/it9175/expected.txt` from the Python tuner; the test replays
init + tune 599143 + tune 473143 against a canned-register IO and compares every
write with the Python command list.
