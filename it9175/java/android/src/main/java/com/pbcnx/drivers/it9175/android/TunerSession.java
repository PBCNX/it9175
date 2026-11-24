package com.pbcnx.drivers.it9175.android;

import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;

import java.io.IOException;

import com.pbcnx.drivers.it9175.It9175Device;
import com.pbcnx.drivers.it9175.Status;

/**
 * One IT9175 session: USB transport, protocol core and TS reader, with an
 * explicit open / close / reopen lifecycle.
 *
 * <p>Android hosts tear a tuner down and bring it back: a detached
 * picture-in-picture task, a source switch, a permission re-grant. The close
 * order matters and this class owns it: stop the reader first (it cancels the
 * queued {@code UsbRequest}s), then close the transport (release the interface
 * and the connection), then drop the core. Closing the connection with a
 * {@code requestWait} still in flight makes that call throw.</p>
 *
 * <p>Re-opening right after a streaming session is the documented warm re-open
 * flake of this part: the LINK processor does not answer the first bring-up
 * query and the reference driver retries after a pause. {@link #open()} does
 * that here - up to {@link #REOPEN_ATTEMPTS} attempts with
 * {@link #REOPEN_DELAY_MS} between them - so a host that tears down and comes
 * back does not have to know about it.</p>
 *
 * <p>Not thread-safe for concurrent use of the same device: one session owns
 * the stick, as the driver always has.</p>
 */
public final class TunerSession {

    /** What the session is doing, for a host that must not tear down its UI. */
    public enum State {
        /** No transport and no core. */
        CLOSED,
        /** Open, tuned, reader armed. */
        OPEN,
        /** The dongle went away: everything is closed, the configuration is kept. */
        SUSPENDED
    }

    /** Bring-up attempts after a warm re-open: the flake clears within ~10 s. */
    public static final int REOPEN_ATTEMPTS = 4;

    /** Pause between bring-up attempts. */
    public static final long REOPEN_DELAY_MS = 2500;

    /** Attempts for a warm {@link #recover()} before giving up. */
    public static final int RECOVER_ATTEMPTS = 2;

    private final UsbManager manager;
    private final byte[] firmware;
    private final AndroidTsReader.Listener listener;

    private UsbDevice device;
    private AndroidTransport transport;
    private It9175Device core;
    private AndroidTsReader reader;
    private String lastError;
    private long lastOpenMillis;
    private volatile State state = State.CLOSED;
    private int lastFrequencyKhz;

    public TunerSession(UsbManager manager, UsbDevice device, byte[] firmware) {
        this(manager, device, firmware, null);
    }

    /**
     * A session whose reader feeds a host-owned sink.
     *
     * <p>Without a listener the session's reader has nowhere to put the TS - a host with its own feed path
     * would have to rebuild it around the session to use {@link #zap(int)}. With one, the reader is armed
     * against that sink and {@code zap()} is adoptable as-is (this is the shape the host asked for,
     * 2026-11-21).
     */
    public TunerSession(UsbManager manager, UsbDevice device, byte[] firmware,
                        AndroidTsReader.Listener listener) {
        this.manager = manager;
        this.device = device;
        this.firmware = firmware;
        this.listener = listener;
    }

    /** Open, bring up the firmware and the tuner scripts, and arm the TS reader. */
    public synchronized void open() throws IOException {
        if (transport != null) {
            throw new IOException("session already open");
        }
        long started = System.currentTimeMillis();
        try {
            openTransportAndCore(0);
        } catch (IOException first) {
            // A warm re-open: the device may still be streaming into an unread
            // endpoint, so the first bring-up query goes unanswered.
            closeTransport();
            openTransportAndCore(REOPEN_ATTEMPTS);
        }
        if (!core.init()) {
            close();
            throw new IOException("tuner init failed");
        }
        reader = new AndroidTsReader(transport.connection(), transport.tsEndpoint(), listener);
        lastOpenMillis = System.currentTimeMillis() - started;
        lastError = null;
        state = State.OPEN;
    }

    private void openTransportAndCore(int attempts) throws IOException {
        IOException last = null;
        for (int attempt = 0; attempt <= attempts; attempt++) {
            if (attempt > 0) {
                sleep(REOPEN_DELAY_MS);
            }
            try {
                transport = AndroidTransport.open(manager, device);
                core = new It9175Device(transport);
                core.bringUp(firmware);
                return;
            } catch (RuntimeException error) {
                last = new IOException("bring-up failed: " + error.getMessage(), error);
                closeTransport();
            }
        }
        throw last != null ? last : new IOException("bring-up failed");
    }

    /** Tune and wait for lock; false means no lock (not an I/O failure). */
    public synchronized boolean tune(int frequencyKhz) {
        if (core == null) {
            lastError = "not open";
            return false;
        }
        if (!core.tune(frequencyKhz)) {
            lastError = "tune refused at " + frequencyKhz + " kHz";
            return false;
        }
        lastFrequencyKhz = frequencyKhz;
        boolean locked = core.waitLock(true);
        lastError = locked ? null : "no lock at " + frequencyKhz + " kHz";
        return locked;
    }

    /**
     * Change channel on the open session: stop the reader, tune, wait for lock, re-arm the reader.
     *
     * <p>This is the vendor's fast zap shape (one open, one init, then frequency changes), and it is
     * the call a player should use instead of closing and re-opening on every channel. The reader
     * must be re-armed around the tune: a queue filled from the previous mux would otherwise be
     * decoded as if it belonged to the new one.
     *
     * @return true when the new channel locked; false when it did not (an I/O failure throws from
     *     {@link #open()} or is reported by {@link #status()}, not here)
     */
    public synchronized boolean zap(int frequencyKhz) {
        if (core == null) {
            lastError = "not open";
            return false;
        }
        AndroidTsReader active = reader;
        if (active != null) {
            active.stop();
        }
        boolean locked = tune(frequencyKhz);
        if (active != null) {
            active.start();
        }
        return locked;
    }

    public synchronized Status status() {
        return core == null ? null : core.status();
    }

    /** Stop the reader, close the transport and forget the core. Safe twice. */
    public synchronized void close() {
        if (reader != null) {
            reader.stop();
            reader = null;
        }
        closeTransport();
        core = null;
        state = State.CLOSED;
    }

    /**
     * The dongle was detached. Release it now - the host may keep its activity,
     * surface and playlist - and remember the frequency for {@link #resume}.
     */
    public synchronized void suspend() {
        if (state != State.OPEN) {
            return;
        }
        close();
        state = State.SUSPENDED;
    }

    /**
     * The dongle came back after a replug: open the new device, retry the warm
     * re-open as {@link #open()} does, and re-tune the channel that was playing.
     * The host only has to hand over the new {@link UsbDevice}.
     *
     * <p>Permission is the host's business ({@code UsbManager.hasPermission});
     * a device without it fails here like any other open.</p>
     */
    public synchronized boolean resume(UsbDevice newDevice) throws IOException {
        if (state != State.SUSPENDED) {
            return false;
        }
        device = newDevice;
        open();
        if (lastFrequencyKhz > 0) {
            // zap(), not tune(): open() creates the reader but does not start it, so a resume that
            // tunes and returns hands the host a locked demod with a silent pipe. That is the same
            // defect tune() had on 2026-11-22, one call later - the host app measured 0 KiB for ~11 s after a
            // resume lock and is taking the row that proves which side owns it (2026-11-23 01:48).
            if (!zap(lastFrequencyKhz)) {
                // A new USB instance does not mean a fresh part: the previous handle can leave the
                // demod suspended, and a warm bring-up then reads a strong signal with snr 0.0 and
                // never locks. recover() forces the upload from its second attempt, which restarts
                // the CPU. Measured on an Android TV box, 2026-11-22 (warm: never locked; cold: 1224 ms).
                if (core != null && core.recover(firmware, RECOVER_ATTEMPTS)) {
                    zap(lastFrequencyKhz);
                }
            }
        }
        return isOpen();
    }

    /** Close and open again, with the warm re-open retry inside {@link #open()}. */
    public synchronized void reopen() throws IOException {
        close();
        open();
    }

    /**
     * The software answer to the power-cycle trap: write the pre-upload sequence, close, and
     * suspend. The chip re-enumerates; the host's {@link UsbAttachWatcher} fires and
     * {@link #resume(UsbDevice)} brings it back (uploading only if the chip came back blank),
     * then re-tunes {@link #lastFrequencyKhz()}.
     *
     * <p>Measured scope (2026-11-20): this recovers a stuck session every time it was needed, and
     * sometimes returns the chip to its boot ROM - it is a recovery path, not a guaranteed chip
     * reset. If the device does not re-appear, the host must tell the user to unplug it.</p>
     *
     * @return true when the sequence was written (the device should re-enumerate)
     */
    public synchronized boolean forceBootAndSuspend() {
        if (core == null) {
            lastError = "not open";
            return false;
        }
        boolean written = core.forceBoot();
        close();
        state = State.SUSPENDED;
        return written;
    }

    /** Warm recovery with retries, without forcing a reset; keeps the current reader. */
    public synchronized boolean recover() {
        if (core == null) {
            lastError = "not open";
            return false;
        }
        boolean ok = core.recover(firmware, RECOVER_ATTEMPTS);
        lastError = ok ? null : "recover failed";
        return ok;
    }

    private void closeTransport() {
        if (transport != null) {
            try {
                transport.close();
            } catch (RuntimeException error) {
                lastError = "close: " + error;
            }
            transport = null;
        }
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    public synchronized boolean isOpen() {
        return transport != null && core != null;
    }

    public synchronized AndroidTsReader reader() {
        return reader;
    }

    public synchronized It9175Device core() {
        return core;
    }

    /** Last tuner failure or the reason the last open failed; null when fine. */
    public synchronized String lastError() {
        return lastError;
    }

    /** How long the last successful open took, including any retry. */
    public synchronized long lastOpenMillis() {
        return lastOpenMillis;
    }

    public synchronized State state() {
        return state;
    }

    /** The channel the last {@link #tune} was asked for, or 0. */
    public synchronized int lastFrequencyKhz() {
        return lastFrequencyKhz;
    }
}
