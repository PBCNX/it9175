package ph.pbcnx.it9175.demo;

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
import android.os.Looper;
import android.util.Log;
import android.widget.Button;
import android.widget.TextView;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;

import ph.pbcnx.it9175.It9175Device;
import ph.pbcnx.it9175.android.AndroidTransport;
import ph.pbcnx.it9175.android.AndroidTsReader;

/**
 * Minimal harness: open the IT9175, upload firmware, init, tune 479.143 MHz and
 * write the aligned TS to the app's external files directory.
 */
public final class MainActivity extends Activity {

    private static final int VENDOR = 0x048D;
    private static final int PRODUCT = 0x275A;
    private static final int FREQ_KHZ = 479143;
    private static final String ACTION_USB = "ph.pbcnx.it9175.demo.USB_PERMISSION";
    private static final String TAG = "it9175-boot";

    private TextView status;
    private UsbManager usbManager;
    private UsbDevice device;
    private AndroidTransport transport;
    private AndroidTsReader reader;
    private OutputStream out;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile long packets;
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
            if (intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false) && device != null) {
                startSession();
            } else {
                setStatus("USB permission denied");
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
            ui.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        status = findViewById(R.id.status);
        findViewById(R.id.stop).setOnClickListener(v -> stopSession());

        usbManager = (UsbManager) getSystemService(Context.USB_SERVICE);
        IntentFilter filter = new IntentFilter(ACTION_USB);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(permission, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(permission, filter);
        }
        begin();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        begin();
    }

    @Override
    protected void onDestroy() {
        try {
            unregisterReceiver(permission);
        } catch (RuntimeException ignored) {
            // not registered
        }
        stopSession();
        super.onDestroy();
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
        if (usbManager.hasPermission(device)) {
            startSession();
            return;
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
                fail("missing firmware at " + firmware + "\n\nadb push firmware.bin " + dir);
                return;
            }
            byte[] image = readAll(firmware);

            transport = AndroidTransport.open(usbManager, device);
            Log.i(TAG, "open ok");
            It9175Device tuner = new It9175Device(transport);
            long started = System.currentTimeMillis();
            String bringUp = tuner.bringUp(image);
            Log.i(TAG, "bringUp " + (System.currentTimeMillis() - started) + " ms: " + bringUp);
            started = System.currentTimeMillis();
            boolean inited = tuner.init();
            Log.i(TAG, "init=" + inited + " in " + (System.currentTimeMillis() - started) + " ms");
            headline = bringUp + "\ninit=" + inited;
            started = System.currentTimeMillis();
            boolean locked = tuner.tune(FREQ_KHZ);
            Log.i(TAG, "tune " + FREQ_KHZ + " lock=" + locked + " in "
                    + (System.currentTimeMillis() - started) + " ms");
            headline += "  tune=" + FREQ_KHZ + "  lock=" + locked;

            File ts = new File(dir, "it9175-demo.ts");
            // Buffered: one unbuffered write per 188-byte packet starved the
            // reader on the phone and cost ~10,000 continuity errors in 20 s.
            out = new BufferedOutputStream(new FileOutputStream(ts), 65536);
            final TsAligner aligner = new TsAligner();
            reader = new AndroidTsReader(transport, new AndroidTsReader.Listener() {
                @Override
                public void onData(byte[] data, int length) {
                    try {
                        packets += aligner.write(data, length, out);
                    } catch (IOException error) {
                        fail("write failed: " + error);
                    }
                }
            });
            reader.start();
            headline += "\n" + ts;
            setStatus(headline);
            ui.post(ticker);
        } catch (Exception error) {
            fail(error.toString());
        }
    }

    private void stopSession() {
        running = false;
        if (reader != null) {
            reader.stop();
            reader = null;
        }
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
