package com.pbcnx.drivers.it9175.demo;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.SystemClock;
import android.os.Looper;
import android.util.Log;
import android.widget.Button;
import android.widget.TextView;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.IOException;
import java.io.OutputStream;

import com.pbcnx.drivers.it9175.It9175Device;
import com.pbcnx.drivers.it9175.android.AndroidTransport;
import com.pbcnx.drivers.it9175.android.AndroidTsReader;
import com.pbcnx.drivers.it9175.android.TunerSession;

/**
 * Minimal harness: open the IT9175, upload firmware, init, tune 479.143 MHz and
 * write the aligned TS to the app's external files directory.
 */
public final class MainActivity extends Activity {

    private static final int VENDOR = 0x048D;
    private static final int PRODUCT = 0x275A;
    private static final int DEFAULT_FREQ_KHZ = 479143;
    private static final String ACTION_USB = "com.pbcnx.drivers.it9175.demo.USB_PERMISSION";
    private static final String TAG = "it9175-boot";
    private static final String EXTRA_FREQ = "freq";
    /** The family's three measured channels: a zap cycle that always locks on an aerial. */
    private static final int[] ZAP_CHANNELS = {479143, 497143, 485143};
    private int zapIndex;
    /** Diagnostic switch: force the permission request even when a grant is cached, so the flag path runs. */
    private boolean forcePermissionRequest;

    private TextView status;
    private UsbManager usbManager;
    private UsbDevice device;
    private AndroidTransport transport;
    private AndroidTsReader reader;
    private OutputStream out;
    private int freqKhz = DEFAULT_FREQ_KHZ;
    private boolean raw;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile long packets;
    private volatile It9175Device core;
    private volatile byte[] image;
    private volatile boolean running;
    private volatile String headline = "";

    private final BroadcastReceiver permission = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!ACTION_USB.equals(intent.getAction())) {
                return;
            }
            UsbDevice granted = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            if (granted != null) {
                device = granted;
            }
            // The receiver is EXPORTED (API 33+ needs it for the system's PendingIntent), so the
            // extra is a hint, not a fact: verify the grant with the UsbManager before opening,
            // or a spoofed broadcast from another app could drive this path (SMSRIO, 2026-11-20).
            boolean extraSaysGranted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false);
            boolean realGrant = device != null && usbManager != null && usbManager.hasPermission(device);
            if (extraSaysGranted && realGrant) {
                startSession();
            } else if (extraSaysGranted && !realGrant) {
                Log.w(TAG, "permission broadcast without a real grant for " + device);
                setStatus("USB permission broadcast did not carry a real grant");
            } else {
                setStatus("USB permission denied");
            }
        }
    };

    /**
     * The vendor app's supervisor pattern: a detach tears the session down, an attach rebuilds it.
     * The old transport is dead after a replug, so recovery on it must fail - rebuilding is the
     * correct move for state 2 (a detach and attach leaves the old transport dead).
     */
    private final BroadcastReceiver hotplug = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            UsbDevice target = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            String action = intent.getAction();
            if (UsbManager.ACTION_USB_DEVICE_DETACHED.equals(action)) {
                if (target != null && target.getVendorId() == VENDOR
                        && target.getProductId() == PRODUCT) {
                    Log.i(TAG, "detached: closing the session");
                    setStatus("dongle detached - waiting for it");
                    stopSession();
                }
            } else if (UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(action)) {
                if (target != null && target.getVendorId() == VENDOR
                        && target.getProductId() == PRODUCT) {
                    Log.i(TAG, "attached: rebuilding the session");
                    device = target;
                    begin();
                }
            }
        }
    };

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            if (!running) {
                return;
            }
            setStatus(headline + "\npackets " + packets);
            AndroidTsReader r = reader;
            // The driver's own TS packet count, beside the host's. The pair settles "is this rate the mux's or the
            // receiver's arithmetic": a 188-byte count and a null-PID count come from the bytes the driver read.
            Log.i(TAG, "ts packets=" + (r == null ? 0 : r.tsPackets())
                    + " nulls=" + (r == null ? 0 : r.tsNulls())
                    + " resync=" + (r == null ? 0 : r.tsResyncs()));
            Log.i(TAG, "packets=" + packets + " reader=" + (r == null ? "none" : r.mode())
                    + " comp=" + (r == null ? 0 : r.completions())
                    + " empty=" + (r == null ? 0 : r.emptyCompletions())
                    + " short=" + (r == null ? 0 : r.shortCompletions())
                    + " timeouts=" + (r == null ? 0 : r.timeouts())
                    + " errors=" + (r == null ? 0 : r.errors())
                    + " recovered=" + (r == null ? 0 : r.recoveries())
                    + " why=" + (r == null ? "" : r.lastRecoveryReason())
                    + " inflight=" + (r == null ? 0 : r.inFlight())
                    + " ready=" + (r == null ? 0 : r.readyDepth())
                    + " carried=" + (r == null ? 0 : r.carriedBytes())
                    + " bytes=" + (r == null ? 0 : r.bytesRead()));
            ui.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        status = findViewById(R.id.status);
        findViewById(R.id.stop).setOnClickListener(v -> stopSession());
        findViewById(R.id.recover).setOnClickListener(v -> recoverNow());
        findViewById(R.id.door).setOnClickListener(v -> {
            // The step-2 line, tappable: open through the door's provider, log the five fields.
            if (device == null) {
                device = findDevice();
            }
            new Thread(this::runDoor, "it9175-door").start();
        });
        findViewById(R.id.zap).setOnClickListener(v -> zapNow());
        findViewById(R.id.restart).setOnClickListener(v -> {
            // close and open again WITHOUT a bus event - the driver-state half of move 4
            stopSession();
            begin();
        });

        usbManager = (UsbManager) getSystemService(Context.USB_SERVICE);
        IntentFilter filter = new IntentFilter(ACTION_USB);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // EXPORTED, not NOT_EXPORTED: the permission result is a PendingIntent broadcast and on
            // API 33+ a NOT_EXPORTED receiver drops it silently - measured by the IT9308 line on
            // 2026-11-20 (it looks exactly like "no dialog appeared").
            //
            // A diagnostic switch: launch with `--ez perm_not_exported true` to force
            // the wrong flag, so the un-taken branch is exercised deliberately instead of waiting for
            // a device that happens to avoid it. The verdict is hasPermission either way.
            boolean forceNotExported = getIntent().getBooleanExtra("perm_not_exported", false);
            forcePermissionRequest = forceNotExported;
            int flag = forceNotExported ? Context.RECEIVER_NOT_EXPORTED : Context.RECEIVER_EXPORTED;
            Log.i(TAG, "permission receiver registered "
                    + (forceNotExported ? "NOT_EXPORTED (forced by the switch)" : "EXPORTED"));
            registerReceiver(permission, filter, flag);
        } else {
            registerReceiver(permission, filter);
        }
        IntentFilter hotplugFilter = new IntentFilter();
        hotplugFilter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
        hotplugFilter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(hotplug, hotplugFilter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(hotplug, hotplugFilter);
        }
        freqKhz = getIntent().getIntExtra(EXTRA_FREQ, DEFAULT_FREQ_KHZ);
        raw = getIntent().getBooleanExtra("raw", false);
        if (getIntent().getBooleanExtra("door", false)) {
            // The step-2 line: open through the door's provider, not through TunerSession.
            new Thread(this::runDoor, "it9175-door").start();
            return;
        }
        begin();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        freqKhz = intent.getIntExtra(EXTRA_FREQ, DEFAULT_FREQ_KHZ);
        raw = intent.getBooleanExtra("raw", false);
        begin();
    }

    @Override
    protected void onDestroy() {
        try {
            unregisterReceiver(permission);
            unregisterReceiver(hotplug);
        } catch (RuntimeException ignored) {
            // not registered
        }
        stopSession();
        super.onDestroy();
    }

    /**
     * The door's own path, for the family's step-2 line: provider.open(...) -> tune -> the five fields.
     *
     * <p>Logcat tag {@code it9175-door}. Launched with {@code --ez door true}; needs the firmware image like any
     * other session (assets in a private build, a push in a public one).
     */
    private void runDoor() {
        if (device == null) {
            Log.i("it9175-door", "door: NOT CALLED - no 048d:275a on the bus");
            return;
        }
        try {
            // External storage can be absent (a headless box returns null): fall back to the internal dir rather
            // than resolving "firmware.bin" against "/" and failing with EROFS.
            File dir = getExternalFilesDir(null);
            if (dir == null) {
                dir = getFilesDir();
            }
            File firmware = new File(dir, "firmware.bin");
            if (!firmware.isFile()) {
                try (InputStream in = getAssets().open("firmware.bin");
                     OutputStream copy = new FileOutputStream(firmware)) {
                    byte[] buffer = new byte[8192];
                    int read;
                    while ((read = in.read(buffer)) > 0) {
                        copy.write(buffer, 0, read);
                    }
                }
            }
            byte[] bytes = readAll(firmware);
            long openedAt = SystemClock.elapsedRealtime();
            final java.util.concurrent.atomic.AtomicLong doorBytes = new java.util.concurrent.atomic.AtomicLong();
            final java.util.concurrent.atomic.AtomicLong firstByteAt = new java.util.concurrent.atomic.AtomicLong();
            final java.util.concurrent.atomic.AtomicLong sinkNs = new java.util.concurrent.atomic.AtomicLong();
            final java.util.concurrent.atomic.AtomicLong sinkCount = new java.util.concurrent.atomic.AtomicLong();
            final java.util.concurrent.atomic.AtomicLong sinkMaxNs = new java.util.concurrent.atomic.AtomicLong();
            com.pbcnx.tuner.Tuner tuner = new com.pbcnx.drivers.it9175.driver.It9175Provider()
                    .open(this, device, bytes, (data, length) -> {
                        long entered = System.nanoTime();
                        firstByteAt.compareAndSet(0, SystemClock.elapsedRealtime());
                        doorBytes.addAndGet(length);
                        long spent = System.nanoTime() - entered;
                        sinkNs.addAndGet(spent);
                        sinkCount.incrementAndGet();
                        sinkMaxNs.accumulateAndGet(spent, Math::max);
                    });
            // The provider returns an UNOPENED Tuner: open() is the host's call, and it is the only
            // method that throws (contract row 1). Skipping it makes tune() answer false in 0 ms.
            tuner.open();
            boolean locked = tuner.tune(freqKhz);
            long tunedAt = SystemClock.elapsedRealtime();
            com.pbcnx.tuner.Tmcc tmcc = tuner.tmccSettled(8, 150);
            String line = String.format(java.util.Locale.US,
                    "door: opened %s, %04x:%04x, firmware %s, tune %d lock %s in %d ms"
                            + " · tmcc %s",
                    tuner.getClass().getName(), device.getVendorId(), device.getProductId(),
                    bytes.length + " B image", freqKhz, locked, tunedAt - openedAt,
                    tmcc == null ? "(-)" : tmcc);
            Log.i("it9175-door", line);
            // The reader-armed question: bytes from the door's own sink, not the demo session's.
            doorBytes.set(0);
            SystemClock.sleep(5000);
            Log.i("it9175-door", "door: bytes " + doorBytes.get() + " after 5000 ms (tune only, no zap)");
            Log.i("it9175-door", "door: sink cost " + (sinkNs.get() / 1_000_000) + " ms over "
                    + sinkCount.get() + " callbacks (max " + (sinkMaxNs.get() / 1_000_000) + " ms)");
            long firstAt = firstByteAt.get();
            Log.i("it9175-door", "door: first bytes " + (firstAt == 0 ? "-" : String.valueOf(firstAt - tunedAt))
                    + " ms after the tune");
            tuner.close();
        } catch (Throwable error) {
            Log.i("it9175-door", "door: FAILED - " + error);
        }
    }

    private void begin() {
        if (running) {
            return;
        }
        device = findDevice();
        if (device == null) {
            setStatus("plug the 048d:275a dongle");
            return;
        }
        if (usbManager.hasPermission(device) && !forcePermissionRequest) {
            startSession();
            return;
        }
        if (forcePermissionRequest) {
            Log.i(TAG, "diagnostic switch: requesting permission despite a cached grant "
                    + "(a cached grant is what hides the receiver-flag branch)");
        }
        PendingIntent intent = PendingIntent.getBroadcast(this, 0,
                new Intent(ACTION_USB).setPackage(getPackageName()),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        usbManager.requestPermission(device, intent);
        setStatus("waiting for USB permission...");
    }

    private UsbDevice findDevice() {
        for (UsbDevice candidate : usbManager.getDeviceList().values()) {
            if (candidate.getVendorId() == VENDOR && candidate.getProductId() == PRODUCT) {
                return candidate;
            }
        }
        return null;
    }

    private void startSession() {
        if (running) {
            return;
        }
        running = true;
        new Thread(this::runSession, "it9175-session").start();
    }

    private void runSession() {
        try {
            File dir = getExternalFilesDir(null);
            if (dir == null) {
                dir = getFilesDir();
            }
            dir.mkdirs();
            File firmware = new File(dir, "firmware.bin");
            if (!firmware.isFile()) {
                // A private build may carry the vendor image in its assets;
                // a fresh install then needs no adb push. A public build has no asset and
                // falls back to the push instruction below.
                try (InputStream in = getAssets().open("firmware.bin");
                     OutputStream copy = new FileOutputStream(firmware)) {
                    byte[] buffer = new byte[8192];
                    int read;
                    while ((read = in.read(buffer)) > 0) {
                        copy.write(buffer, 0, read);
                    }
                    copy.flush();
                    Log.i(TAG, "firmware extracted from assets: " + firmware.length() + " bytes");
                } catch (IOException missing) {
                    fail("missing firmware at " + firmware + "\n\nadb push firmware.bin " + dir
                            + "\n(no bundled asset in this build)");
                    return;
                }
            }
            image = readAll(firmware);
            int cycles = getIntent().getIntExtra("cycles", 0);
            if (cycles > 0) {
                runCycles(cycles, freqKhz, image);
                return;
            }

            transport = AndroidTransport.open(usbManager, device);
            Log.i(TAG, "open ok");
            byte[] firmwareImage = image;
            It9175Device tuner = new It9175Device(transport);
            core = tuner;
            long started = System.currentTimeMillis();
            String bringUp = tuner.bringUp(image);
            Log.i(TAG, "bringUp " + (System.currentTimeMillis() - started) + " ms: " + bringUp);
            started = System.currentTimeMillis();
            boolean inited = tuner.init();
            Log.i(TAG, "init=" + inited + " in " + (System.currentTimeMillis() - started) + " ms");
            headline = bringUp + "\ninit=" + inited;
            started = System.currentTimeMillis();
            boolean locked = tuner.tune(freqKhz);
            Log.i(TAG, "tune " + freqKhz + " lock=" + locked + " in "
                    + (System.currentTimeMillis() - started) + " ms");
            headline += "  tune=" + freqKhz + "  lock=" + locked;
            // Rule 8 of the family testing standard: the demod's own codeword, read AFTER the lock
            // and BEFORE the stream starts. Reading TMCC after the pump starts can stall it.
            try {
                // 0x0000 reads as a legitimate "2K / 1/32", so a reading taken before the demod
                // has decoded TMCC looks plausible and is wrong. Retry until the decoder reports
                // a channel (at least one layer with segments), and say so when it never does.
                // settled, not merely valid: after a lock or a zap the block can still describe
                // the previous mux (IT9308: transient for a few hundred ms; LME2510: two agreeing reads)
                com.pbcnx.drivers.it9175.Tmcc reading = tuner.tmccSettled(10, 150);
                if (reading != null) {
                    String line = "tmcc " + reading;
                    Log.i(TAG, line);
                    headline += "\n" + line;
                    // this chip exposes no EWBS flag (five methods, 2026-11-20) - say so, do not print 0
                    headline += "\n  ewbs: n/a (no flag on this chip; see the IIP/PMT paths)";
                } else {
                    Log.i(TAG, "tmcc not decoded (no valid reading after 2 s)");
                    headline += "\ntmcc not decoded (no valid reading after 2 s)";
                }
            } catch (RuntimeException error) {
                Log.i(TAG, "tmcc unreadable: " + error);
                headline += "\ntmcc unreadable (" + error.getMessage() + ")";
            }

            File ts = new File(getFilesDir(), raw ? "it9175-raw.bin" : "it9175-demo.ts");
            // Buffered: one unbuffered write per 188-byte packet starved the
            // reader on the phone and cost ~10,000 continuity errors in 20 s.
            out = new BufferedOutputStream(new FileOutputStream(ts), 65536);
            final TsAligner aligner = new TsAligner();
            reader = new AndroidTsReader(transport, new AndroidTsReader.Listener() {
                @Override
                public void onData(byte[] data, int length) {
                    try {
                        if (raw) {
                            out.write(data, 0, length);   // before any alignment
                            packets += length / 188;
                        } else {
                            packets += aligner.write(data, length, out);
                        }
                    } catch (IOException error) {
                        fail("write failed: " + error);
                    }
                }
            });
            // The mixed-buffer thread below is a pull-mode reader; do not also start the
            // listener loop, or two threads would call requestWait on one connection.
            if (getIntent().getBooleanExtra("shortdst", false)) {
                // Reproduce the app's block pool with mixed block sizes: every third read
                // uses a 20,000-byte buffer. Before the reader kept the tail, each of those
                // reads dropped part of a 32 KB completion and the demux lost alignment.
                Thread mixed = new Thread(() -> {
                    byte[] full = new byte[AndroidTsReader.BATCH_BYTES];
                    byte[] small = new byte[20000];
                    int turn = 0;
                    while (running) {
                        byte[] buffer = (turn++ % 3 == 0) ? small : full;
                        try {
                            int n = reader.read(buffer, 500);
                            if (n > 0) {
                                if (raw) {
                                    out.write(buffer, 0, n);
                                    packets += n / 188;
                                } else {
                                    packets += aligner.write(buffer, n, out);
                                }
                            }
                        } catch (IOException error) {
                            fail("write failed: " + error);
                            return;
                        }
                    }
                }, "it9175-demo-mixed");
                mixed.setDaemon(true);
                mixed.start();
            } else {
                reader.start();
            }
            if (getIntent().getBooleanExtra("poll", false)) {
                final It9175Device pollDevice = tuner;
                Thread poller = new Thread(() -> {
                    while (running) {
                        try {
                            Thread.sleep(1000);
                        } catch (InterruptedException stop) {
                            return;
                        }
                        if (!running) {
                            return;
                        }
                        pollDevice.status();   // the app's 1 Hz status poll, same link
                    }
                }, "it9175-demo-poll");
                poller.setDaemon(true);
                poller.start();
            }
            headline += "\n" + ts;
            setStatus(headline);
            ui.post(ticker);
        } catch (Exception error) {
            fail(error.toString());
        }
    }

    /** Open/tune/read/close N times: the teardown and warm re-open path a PiP task needs. */
    private void runCycles(int cycles, int freq, byte[] image) {
        for (int i = 1; i <= cycles; i++) {
            long started = System.currentTimeMillis();
            TunerSession session = new TunerSession(usbManager, device, image);
            try {
                session.open();
                boolean locked = session.tune(freq);
                int firstRead = 0;
                AndroidTsReader reader = session.reader();
                if (reader != null) {
                    byte[] buffer = new byte[AndroidTsReader.BATCH_BYTES];
                    for (int attempt = 0; attempt < 10 && firstRead == 0; attempt++) {
                        int n = reader.read(buffer, 500);
                        if (n > 0) {
                            firstRead = n;
                        }
                    }
                }
                Log.i(TAG, "cycle " + i + "/" + cycles + ": open=" + session.lastOpenMillis()
                        + "ms locked=" + locked + " firstRead=" + firstRead
                        + " total=" + (System.currentTimeMillis() - started) + "ms err=" + session.lastError());
            } catch (IOException error) {
                Log.e(TAG, "cycle " + i + "/" + cycles + " failed after "
                        + (System.currentTimeMillis() - started) + "ms: " + error);
            } finally {
                session.close();
                Log.i(TAG, "cycle " + i + " closed");
            }
        }
        setStatus("cycles done");
    }

    /**
     * The recovery primitive from the UI: warm bring-up + tuner scripts, retried, no reset.
     * A wedge that outlives this needs forceBootAndSuspend() and a re-attach (the adapter's
     * UsbAttachWatcher path). After a replug the old transport is dead, so recover() correctly
     * returns false - the hotplug receiver rebuilds the session instead.
     */
    private void recoverNow() {
        final It9175Device local = core;
        final byte[] localImage = image;
        if (!running || local == null || localImage == null) {
            // A closed session (STOP, or a detach the receiver has already handled) cannot be
            // recovered on its dead transport: rebuild instead. Same rule as after a replug.
            Log.i(TAG, "recover: no live session, rebuilding");
            setStatus("recovering: rebuilding the session");
            begin();
            return;
        }
        new Thread(() -> {
            long started = System.currentTimeMillis();
            boolean ok = local.recover(localImage, 2);
            long took = System.currentTimeMillis() - started;
            Log.i(TAG, "recover=" + ok + " in " + took + " ms");
            headline += "\nrecover=" + ok + " in " + took + " ms";
            if (ok) {
                boolean locked = local.tune(freqKhz);
                Log.i(TAG, "recover re-tune " + freqKhz + " lock=" + locked);
                headline += "  re-tune lock=" + locked;
            }
        }, "it9175-recover").start();
    }

    /** Change channel on the live session - the vendor's fast zap: stop reader, tune, re-arm. */
    private void zapNow() {
        final It9175Device live = core;
        if (live == null) {
            setStatus("not running - start a session first");
            return;
        }
        new Thread(() -> {
            int target = ZAP_CHANNELS[zapIndex++ % ZAP_CHANNELS.length];
            long began = SystemClock.elapsedRealtime();
            if (reader != null) {
                reader.stop();
            }
            boolean locked = live.tune(target);
            if (reader != null) {
                reader.start();
            }
            long millis = SystemClock.elapsedRealtime() - began;
            String line = "zap " + target + " kHz: " + millis + " ms lock=" + locked;
            // The TMCC block is transient for a few hundred ms after a switch (IT9308 measured it):
            // read it only once the decoder reports a real channel, or the display shows the old mux.
            com.pbcnx.drivers.it9175.Tmcc switched = live.tmccSettled(8, 100);
            line += (switched != null)
                    ? "\n  tmcc " + switched
                    : "\n  tmcc did not settle (block transient after a switch, or not decoded)";
            Log.i(TAG, line);
            freqKhz = target;
            setStatus((headline.isEmpty() ? "" : headline + "\n") + line
                    + "\npackets " + packets);
        }, "it9175-zap").start();
    }

    private void stopSession() {
        running = false;
        if (reader != null) {
            reader.stop();
            reader = null;
        }
        core = null;                       // the transport dies with it
        if (transport != null) {
            transport.close();
            transport = null;
        }
        if (out != null) {
            try {
                out.flush();
                out.close();
            } catch (IOException ignored) {
                // closing
            }
            out = null;
        }
        setStatus((headline.isEmpty() ? "" : headline + "\n") + "stopped at packets " + packets);
    }

    private void fail(String message) {
        running = false;
        closeOutput();
        setStatus("error: " + message);
    }

    private void closeOutput() {
        if (out != null) {
            try {
                out.flush();
                out.close();
            } catch (IOException ignored) {
                // closing
            }
            out = null;
        }
    }

    private void setStatus(String text) {
        runOnUiThread(() -> status.setText(text));
    }

    private static byte[] readAll(File file) throws IOException {
        byte[] data = new byte[(int) file.length()];
        try (FileInputStream in = new FileInputStream(file)) {
            int offset = 0;
            while (offset < data.length) {
                int read = in.read(data, offset, data.length - offset);
                if (read < 0) {
                    break;
                }
                offset += read;
            }
        }
        return data;
    }
}
