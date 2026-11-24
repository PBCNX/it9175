package com.pbcnx.drivers.it9175;

/**
 * Tells a stalled stream from an empty channel, and from a dead handle.
 *
 * <p>The family rule (2026-11-20): <b>silence alone is not a disconnect.</b> An empty channel is
 * silent with the device present; a pulled stick is silent with the device absent; a wedge is silent
 * with the device present <em>and</em> the demod locked. A host that reacts to silence alone either
 * chases ghosts on dead multiplexes or misses real detaches.</p>
 *
 * <p>Feed it progress on every read that returns data, then ask it in the watchdog. It is plain
 * Java with no Android types, so every host (and the JVM self-test) can use the same logic.</p>
 *
 * <pre>
 *   detector.progress(SystemClock.elapsedRealtime());        // a packet arrived
 *   long silent = detector.silentMillis(SystemClock.elapsedRealtime());
 *   String hint = StallDetector.hint(locked, silent, devicePresent);
 *   if (hint != null) ask(hint);                             // recover, or the replug message
 * </pre>
 */
public final class StallDetector {

    /** How long without a packet counts as a stall (2 s: the Python CLI default). */
    public static final long DEFAULT_STALL_MILLIS = 2000;

    private final long stallMillis;
    private long lastProgressMillis;

    public StallDetector() {
        this(DEFAULT_STALL_MILLIS);
    }

    public StallDetector(long stallMillis) {
        this.stallMillis = stallMillis > 0 ? stallMillis : DEFAULT_STALL_MILLIS;
    }

    /** Record that data arrived at {@code nowMillis}. */
    public void progress(long nowMillis) {
        lastProgressMillis = nowMillis;
    }

    /** Milliseconds since the last packet, or 0 when that is still inside the stall window. */
    public long silentMillis(long nowMillis) {
        if (lastProgressMillis == 0) {
            return nowMillis >= stallMillis ? nowMillis : 0;
        }
        long silent = nowMillis - lastProgressMillis;
        return silent >= stallMillis ? silent : 0;
    }

    /** True once nothing has progressed for the configured window. */
    public boolean stalled(long nowMillis) {
        return silentMillis(nowMillis) > 0;
    }

    /**
     * The one-line advice a host should show, or null when there is nothing to act on.
     *
     * <p>Silent + unlocked + present is an <b>empty channel</b>: the right action is none. Silent +
     * absent is a detach: rebuild on attach. Silent + locked + present is a <b>wedge</b>: try the
     * recovery primitive first, the cable only if that fails.</p>
     */
    public static String hint(long silentMillis, boolean locked, boolean devicePresent) {
        if (silentMillis <= 0) {
            return null;
        }
        if (!devicePresent) {
            return "device lost: unplug and replug the tuner";
        }
        if (locked) {
            return "locked but no TS data: try recover; if it fails, unplug/replug (a USB reset "
                    + "does not clear this device)";
        }
        return null;
    }
}
