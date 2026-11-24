package com.pbcnx.drivers.it9175.android;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.os.Build;

/**
 * Watches the dongle's detach/attach so a host can keep its activity, surface
 * and playlist alive and rebuild the tuner quietly - the seamless replug the
 * vendor app does (measured 2026-11-19: same process, the tuner re-opened and
 * re-tuned on the attach with no user action).
 *
 * <p>Typical host wiring:</p>
 * <pre>
 * session.open();  session.tune(497143);
 * UsbAttachWatcher watcher = UsbAttachWatcher.register(context, usbManager,
 *     new UsbAttachWatcher.Listener() {
 *         public void onDongleDetached() { session.suspend(); }        // keep the UI
 *         public void onDongleAttached(UsbDevice device) {
 *             try { session.resume(device); } catch (IOException e) { showReplugHint(); }
 *         }
 *     });
 * </pre>
 *
 * <p>{@link #register} takes the {@link UsbManager} so the host can check
 * {@code hasPermission(device)} before resuming; the runtime receiver is
 * limited to this package on API 33+ and is not exported anywhere.</p>
 */
public final class UsbAttachWatcher extends BroadcastReceiver {

    /** What the host does when the dongle comes and goes. */
    public interface Listener {
        /** The stick was unplugged; release it, keep everything else. */
        void onDongleDetached();

        /** The stick was plugged back; hand the device to {@link TunerSession#resume}. */
        void onDongleAttached(UsbDevice device);
    }

    public static final int VENDOR_ID = 0x048D;
    public static final int PRODUCT_ID = 0x275A;

    private final UsbManager manager;
    private final Listener listener;
    private boolean registered;

    private UsbAttachWatcher(UsbManager manager, Listener listener) {
        this.manager = manager;
        this.listener = listener;
    }

    /** Register for attach/detach; call {@link #close()} when the host goes away. */
    public static UsbAttachWatcher register(Context context, UsbManager manager, Listener listener) {
        UsbAttachWatcher watcher = new UsbAttachWatcher(manager, listener);
        IntentFilter filter = new IntentFilter();
        filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(watcher, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(watcher, filter);
        }
        watcher.registered = true;
        return watcher;
    }

    /** Unregister from the same context that registered. Safe twice. */
    public synchronized void close(Context context) {
        if (!registered) {
            return;
        }
        registered = false;
        try {
            context.unregisterReceiver(this);
        } catch (IllegalArgumentException already) {
            // not registered any more
        }
    }

    /** Whether the app may open this device right now (permission survives a replug on most hosts). */
    public boolean hasPermission(UsbDevice device) {
        return manager.hasPermission(device);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        UsbDevice device = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
        if (device == null) {
            return;
        }
        if (device.getVendorId() != VENDOR_ID || device.getProductId() != PRODUCT_ID) {
            return;
        }
        if (UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(action)) {
            listener.onDongleAttached(device);
        } else if (UsbManager.ACTION_USB_DEVICE_DETACHED.equals(action)) {
            listener.onDongleDetached();
        }
    }
}
