package com.pbcnx.drivers.it9175.android;

import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbRequest;
import android.os.Build;
import android.os.SystemClock;
import android.util.Log;

import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.TimeoutException;

import com.pbcnx.drivers.it9175.TsReader;

/**
 * MPEG-TS reader for the IT9175 {@code 0x84} endpoint: queued, order-preserving,
 * bounded.
 *
 * <p>Eight {@code UsbRequest}s of 32,768 bytes are kept in flight. Each
 * submission carries a sequence number, and a completion's data belongs to the
 * sequence that was armed at submission time - not to the order in which
 * completions happen to be returned. {@link #read(byte[], int)} hands data over
 * in sequence order only; a completion that arrives early keeps its buffer and
 * waits for its turn. The USB bulk stream is a byte stream, so a reader that
 * hands over in completion order can splice it, and a spliced stream shows up
 * downstream as a steady sync-loss rate.</p>
 *
 * <p>No copy is made on the hot path: a completion keeps its buffer, and the
 * request is re-armed with a spare buffer from a small pool (eight buffers in
 * total). If the pool is empty because the host is behind, the request waits
 * unarmed and is re-armed when a handed-over buffer comes back - the queue
 * shrinks under backpressure instead of dropping data or stalling inside
 * {@code requestWait}. Memory is bounded by the eight buffers, so nothing is
 * ever discarded except on a halt recovery.</p>
 *
 * <p>A failed wait, or three consecutive timeouts, clears the endpoint halt
 * (standard CLEAR_FEATURE(ENDPOINT_HALT), bmRequestType 0x02, bRequest 0x01)
 * and re-arms the queue. That is the only case where data in flight is
 * discarded.</p>
 *
 * <p>{@link #read(byte[], int)} is the pull API (one owner thread; the app's
 * read loop). {@link #start()} is the listener API used by the demo app. Do not
 * mix both on one instance: {@code requestWait} must have a single caller. The
 * buffer handed to {@link Listener#onData} is reused between reads.</p>
 *
 * <p>Before Android 8 (API 26) the timed {@code requestWait} does not exist;
 * there the reader falls back to the blocking transfer, which is the old
 * behaviour rather than a hang.</p>
 */
public final class AndroidTsReader implements TsReader {

    /** Called on the reader thread with a reusable buffer. */
    public interface Listener {
        void onData(byte[] data, int length);
    }

    /** 32,768: a 512-byte multiple, the reference driver's read size. */
    public static final int BATCH_BYTES = AndroidTransport.TS_BATCH_BYTES;

    /** Requests kept in flight: 8 x 32,768 = 256 KiB of slack at 17 Mbps. */
    /**
     * Requests in flight. Eight gave 8 x 32 KB = 256 KB of slack - about 130 ms at a 15.5 Mbps mux - and the
     * listener runs INLINE on the read thread, so any host stall longer than that overflowed the device's FIFO and
     * lost a buffer-sized span. Measured on a 12 MB capture on an Android TV box (2026-11-23): ~437 bursts, each about
     * 32 packets, with every PID showing almost the same number of continuity events (405-437) - the signature of
     * whole spans missing rather than packets scattered. Thirty-two doubles the slack per buffer class and, with
     * BUFFER_COUNT = 3 x depth, gives ~3 MB of in-flight allowance: the same order as the host's own demux slack.
     */
    public static final int QUEUE_DEPTH = 32;

    /**
     * Buffers = 3 x QUEUE_DEPTH: eight armed, sixteen spare. A completion takes
     * a spare and re-arms at once, so the device always sees eight URBs; the
     * filled buffer waits in the ordered map until the host reads it. With only
     * one buffer per request the pipeline drains to one armed URB after the
     * first burst, which leaves the demodulator's FIFO ~24 ms of slack and
     * shows up as steady packet loss - measured on the Android TV box 2026-11-18
     * (delivery maxGapMs 29-32, CC/sync errors every window).
     */
    private static final int BUFFER_COUNT = QUEUE_DEPTH * 3;

    /**
     * A run of this many timeouts clears the halt and re-arms the queue: ~10 s
     * at the 500 ms wait. A clear costs the in-flight pipeline (up to 24
     * buffers), so it is reserved for a device that has genuinely stopped
     * delivering, not for the jitter a busy host produces.
     */
    private static final int RESTART_AFTER_TIMEOUTS = 20;

    /**
     * The same clear, for a reader that has NOT delivered a single byte yet: two waits (~1 s), not twenty.
     *
     * <p>A reader that is arming is not being protected from churn - there is no pipeline to preserve and no consumer
     * to protect. It is waiting for a queue that never armed, and on a device that has just been handed over while
     * another stick's session was torn down the endpoint can arrive halted. Measured on an Android TV box, 2026-11-23: a
     * swap into this part tuned and locked in 2.1 s, then delivered nothing for 11.0 s - which is 20 x 500 ms plus
     * one wait, this constant. The device was fine; the counter was patient. Two waits are enough to tell "arming"
     * from "jitter" without costing eleven seconds of black screen.
     */
    private static final int FIRST_ARM_AFTER_TIMEOUTS = 2;

    /**
     * A failed wait (an exception from {@code requestWait}) is the halt
     * signature - a timeout is not. Two in a row before clearing, so a single
     * transient failure does not cost the pipeline.
     */
    private static final int CLEAR_AFTER_ERRORS = 2;

    private static final int TIMEOUT_MS = 500;
    private static final String TAG = "It9175Ts";

    private static final class Chunk {
        final ByteBuffer buffer;
        final int length;

        Chunk(ByteBuffer buffer, int length) {
            this.buffer = buffer;
            this.length = length;
        }
    }

    private final UsbDeviceConnection connection;
    private final UsbEndpoint endpoint;
    private final Listener listener;

    private final List<UsbRequest> requests = new ArrayList<>();
    private final Map<UsbRequest, Integer> slotOf = new IdentityHashMap<>();
    private final ByteBuffer[] slotBuffer = new ByteBuffer[QUEUE_DEPTH];
    private final long[] queuedAt = new long[QUEUE_DEPTH];
    private final TreeMap<Long, Chunk> ready = new TreeMap<>();
    private final ArrayDeque<ByteBuffer> spares = new ArrayDeque<>();
    private final ArrayDeque<UsbRequest> unarmed = new ArrayDeque<>();
    private final Object pipeLock = new Object();

    private boolean queued;
    private long nextSubmit;
    private long nextHandover;
    private int consecutiveTimeouts;
    private int consecutiveErrors;

    private volatile boolean running;
    private volatile int generation;
    private Thread thread;

    // Read-path telemetry, for the host's heartbeat. Not printed here: the app
    // decides how much to say.
    private volatile long completions;

    /** TS packets handed to the listener, and how many of them were null packets (PID 0x1FFF). */
    private volatile long tsPackets;
    private volatile long tsBytes;
    private volatile long tsLoggedAt;
    private volatile long tsNulls;
    private volatile long tsResyncs;
    private volatile long emptyCompletions;
    private volatile long shortCompletions;
    private volatile long timeouts;
    private volatile long errors;
    private volatile long recoveries;
    private volatile long timeoutRecoveries;
    private volatile long errorRecoveries;
    private volatile String lastRecoveryReason = "";
    private volatile long bytesRead;
    private volatile long droppedBytes;
    private volatile long carriedBytes;
    private volatile int armed;
    private volatile String mode = "none";

    /** Bytes of a completion that did not fit the caller's buffer, kept for the next read. */
    private byte[] carry;
    private int carryLength;
    private int carryOffset;

    public AndroidTsReader(AndroidTransport transport, Listener listener) {
        this(transport.connection(), transport.tsEndpoint(), listener);
    }

    public AndroidTsReader(UsbDeviceConnection connection, UsbEndpoint endpoint, Listener listener) {
        this.connection = connection;
        this.endpoint = endpoint;
        this.listener = listener;
    }

    // -- pull API -----------------------------------------------------------

    @Override
    public int read(byte[] dst, int timeoutMs) {
        if (dst == null || dst.length == 0) {
            return -1;
        }
        synchronized (pipeLock) {
            if (carryLength > 0) {
                int copy = Math.min(carryLength, dst.length);
                System.arraycopy(carry, carryOffset, dst, 0, copy);
                carryOffset += copy;
                carryLength -= copy;
                if (carryLength == 0) {
                    carry = null;
                    carryOffset = 0;
                }
                completions++;
                bytesRead += copy;
                if (copy < dst.length) {
                    shortCompletions++;
                }
                return copy;
            }
        }
        if (ensurePipeline()) {
            return readQueued(dst, timeoutMs);
        }
        int received = connection.bulkTransfer(endpoint, dst, dst.length, timeoutMs);
        if (received > 0) {
            completions++;
            bytesRead += received;
            if (received < dst.length) {
                shortCompletions++;
            }
        } else if (received == 0) {
            emptyCompletions++;
            timeouts++;
        } else {
            timeouts++;
        }
        return received;
    }

    /** One read with the driver's 500 ms timeout. */
    public int readBatch(byte[] buffer) {
        return read(buffer, TIMEOUT_MS);
    }

    private int readQueued(byte[] dst, int timeoutMs) {
        int wait = timeoutMs > 0 ? timeoutMs : TIMEOUT_MS;
        long deadline = System.nanoTime() + wait * 1_000_000L;
        while (true) {
            synchronized (pipeLock) {
                Chunk chunk = takeReadyLocked();
                if (chunk != null) {
                    int copy = Math.min(chunk.length, dst.length);
                    chunk.buffer.position(0);
                    chunk.buffer.get(dst, 0, copy);
                    if (copy < chunk.length) {
                        // The caller's buffer is smaller than a completion: keep the tail for
                        // the next read instead of dropping it. Dropping it would cut the byte
                        // stream mid-packet and the demux would resynchronise.
                        int extra = chunk.length - copy;
                        carry = new byte[extra];
                        chunk.buffer.get(carry, 0, extra);
                        carryOffset = 0;
                        carryLength = extra;
                        carriedBytes += extra;
                        shortCompletions++;
                    }
                    chunk.buffer.clear();
                    rearmOrHoldLocked(chunk.buffer);
                    completions++;
                    bytesRead += copy;
                    if (copy < dst.length) {
                        shortCompletions++;
                    }
                    consecutiveTimeouts = 0;
                    return copy;
                }
            }
            long remaining = (deadline - System.nanoTime()) / 1_000_000L;
            if (remaining <= 0) {
                onTimeout();
                return -1;
            }
            UsbRequest completed;
            try {
                completed = connection.requestWait(remaining);
            } catch (TimeoutException timedOut) {
                onTimeout();
                return -1;
            } catch (RuntimeException error) {
                Log.w(TAG, "requestWait failed: " + error);
                errors++;
                consecutiveErrors++;
                if (consecutiveErrors >= CLEAR_AFTER_ERRORS) {
                    consecutiveErrors = 0;
                    recover("request-wait");
                }
                return -1;
            }
            if (completed != null) {
                serviceCompletion(completed);
            }
        }
    }

    /** Take the next chunk only when its sequence is the one expected next. */
    private Chunk takeReadyLocked() {
        Map.Entry<Long, Chunk> first = ready.firstEntry();
        if (first == null || first.getKey() != nextHandover) {
            return null;
        }
        Chunk chunk = ready.pollFirstEntry().getValue();
        nextHandover++;
        return chunk;
    }

    /** A freed data buffer goes to an unarmed request, or back to the pool. */
    private void rearmOrHoldLocked(ByteBuffer buffer) {
        UsbRequest request = unarmed.poll();
        if (request == null) {
            spares.add(buffer);
            return;
        }
        Integer slot = slotOf.get(request);
        if (slot == null) {
            spares.add(buffer);
            return;
        }
        queuedAt[slot] = nextSubmit++;
        slotBuffer[slot] = buffer;
        if (!request.queue(buffer)) {
            Log.w(TAG, "re-arm failed");
            slotBuffer[slot] = null;
            queued = false;
            spares.add(buffer);
        } else {
            armed++;
        }
    }

    /** Copy-less completion: keep the filled buffer, re-arm with a spare. */
    private void serviceCompletion(UsbRequest completed) {
        synchronized (pipeLock) {
            Integer slot = slotOf.get(completed);
            if (slot == null) {
                return;   // a completion from a cancelled request of an earlier pipeline
            }
            ByteBuffer buffer = slotBuffer[slot];
            if (buffer == null) {
                return;
            }
            int length = buffer.position();
            long sequence = queuedAt[slot];
            slotBuffer[slot] = null;
            armed--;   // this request is no longer in flight
            if (length <= 0) {
                // Nothing carried: hand the same buffer straight back.
                emptyCompletions++;
                queuedAt[slot] = nextSubmit++;
                slotBuffer[slot] = buffer;
                buffer.clear();
                if (completed.queue(buffer)) {
                    armed++;
                } else {
                    queued = false;
                }
                return;
            }
            ready.put(sequence, new Chunk(buffer, length));
            // Data is flowing: a late completion for the next sequence is not a stall.
            consecutiveTimeouts = 0;
            consecutiveErrors = 0;
            ByteBuffer spare = spares.poll();
            if (spare != null) {
                queuedAt[slot] = nextSubmit++;
                slotBuffer[slot] = spare;
                if (completed.queue(spare)) {
                    armed++;
                } else {
                    Log.w(TAG, "re-arm failed");
                    slotBuffer[slot] = null;
                    queued = false;
                    spares.add(spare);
                }
            } else {
                unarmed.add(completed);   // re-armed when a handed-over buffer returns
            }
        }
    }

    private void onTimeout() {
        timeouts++;
        consecutiveTimeouts++;
        int threshold = bytesRead == 0 ? FIRST_ARM_AFTER_TIMEOUTS : RESTART_AFTER_TIMEOUTS;
        if (consecutiveTimeouts >= threshold) {
            consecutiveTimeouts = 0;
            recover("timeout-run");
        }
    }

    // -- pipeline -----------------------------------------------------------

    private boolean ensurePipeline() {
        synchronized (pipeLock) {
            if (queued) {
                return true;
            }
            if (Build.VERSION.SDK_INT < 26) {
                // requestWait(long) is API 26; below it keep the old blocking path.
                return false;
            }
            try {
                for (int i = 0; i < QUEUE_DEPTH; i++) {
                    UsbRequest request = new UsbRequest();
                    if (!request.initialize(connection, endpoint)) {
                        cancelLocked();
                        return false;
                    }
                    ByteBuffer buffer = ByteBuffer.allocateDirect(BATCH_BYTES);
                    if (!request.queue(buffer)) {
                        request.cancel();
                        cancelLocked();
                        return false;
                    }
                    requests.add(request);
                    slotOf.put(request, i);
                    slotBuffer[i] = buffer;
                    queuedAt[i] = nextSubmit++;
                }
                for (int i = QUEUE_DEPTH; i < BUFFER_COUNT; i++) {
                    spares.add(ByteBuffer.allocateDirect(BATCH_BYTES));
                }
                armed = QUEUE_DEPTH;
            } catch (RuntimeException error) {
                Log.w(TAG, "queued pipeline failed, blocking fallback: " + error);
                cancelLocked();
                return false;
            }
            queued = true;
            mode = "queued";
            Log.i(TAG, "queued pipeline: " + QUEUE_DEPTH + " x " + BATCH_BYTES + " B, ordered");
            return true;
        }
    }

    /**
     * Clear a halted endpoint and re-arm; in-flight data is discarded.
     *
     * @param reason {@code "request-wait"} for a failed wait (the halt
     *               signature) or {@code "timeout-run"} for a long silence
     */
    private void recover(String reason) {
        recoveries++;
        lastRecoveryReason = reason;
        if ("timeout-run".equals(reason)) {
            timeoutRecoveries++;
        } else {
            errorRecoveries++;
        }
        try {
            int address = endpoint.getAddress();
            // bmRequestType 0x02 (host-to-device, standard, endpoint),
            // bRequest 0x01 (CLEAR_FEATURE), wValue 0 (ENDPOINT_HALT).
            connection.controlTransfer(0x02, 0x01, 0x00, address, null, 0, 1000);
        } catch (RuntimeException error) {
            Log.w(TAG, "clearHalt failed: " + error);
        }
        synchronized (pipeLock) {
            cancelLocked();
        }
        ensurePipeline();
    }

    private void cancelLocked() {
        for (UsbRequest request : requests) {
            try {
                request.cancel();
            } catch (RuntimeException ignored) {
                // already cancelled, or the connection is gone
            }
        }
        requests.clear();
        slotOf.clear();
        ready.clear();
        spares.clear();
        unarmed.clear();
        for (int i = 0; i < QUEUE_DEPTH; i++) {
            slotBuffer[i] = null;
            queuedAt[i] = 0;
        }
        nextSubmit = 0;
        nextHandover = 0;
        consecutiveTimeouts = 0;
        consecutiveErrors = 0;
        carry = null;
        carryLength = 0;
        carryOffset = 0;
        armed = 0;
        queued = false;
        mode = "none";
    }

    // -- listener API (demo app) --------------------------------------------

    public synchronized void start() {
        if (running) {
            return;
        }
        if (thread != null && thread.isAlive()) {
            return; // a previous loop has not exited
        }
        if (listener == null) {
            throw new IllegalStateException("start() needs a Listener; use read() otherwise");
        }
        ensurePipeline();
        int gen = ++generation;
        running = true;
        thread = new Thread(() -> loop(gen), "it9175-ts");
        thread.setDaemon(true);
        thread.start();
    }

    private void loop(int gen) {
        byte[] buffer = new byte[BATCH_BYTES];
        while (running && gen == generation) {
            int received;
            try {
                received = read(buffer, TIMEOUT_MS);
            } catch (RuntimeException error) {
                Log.w(TAG, "read failed: " + error);
                break;
            }
            if (received > 0) {
                countPackets(buffer, received);
                listener.onData(buffer, received);
                long now = SystemClock.elapsedRealtime();
                if (tsLoggedAt == 0) {
                    tsLoggedAt = now;
                } else if (now - tsLoggedAt >= 5000) {
                    // Printed here rather than exposed: the provider hands the host the contract's Tuner, so a
                    // host cannot call tsPackets(). A line in the log reaches every host and costs no contract change.
                    Log.i(TAG, "ts " + tsPackets + " packets, " + tsNulls + " nulls, " + tsBytes + " B in "
                            + (now - tsLoggedAt) + " ms, " + tsResyncs + " resyncs");
                    tsLoggedAt = now;
                }
            }
            // received <= 0 is a timeout, a detach, or no lock yet: keep waiting
        }
        if (gen == generation) {
            running = false;
        }
    }

    /**
     * Count the TS packets in one delivered buffer.
     *
     * <p>This is the driver's own count, so a host can ask <em>the thing that read the bytes</em> how many packets it
     * carried - the number that settles "is this rate the mux's, or the receiver's arithmetic". It resynchronises on the
     * 0x47 sync byte rather than assuming the buffer starts a packet, because a 15,040-byte read need not be
     * packet-aligned at the seam.
     */
    private void countPackets(byte[] data, int length) {
        tsBytes += length;
        int i = 0;
        boolean resynced = false;
        while (i + 188 <= length) {
            if (data[i] != 0x47) {
                // one event per run of lost alignment, not per byte skipped: a resync is a jump, and counting bytes
                // would make "92 resyncs for 2 packets" - which is what the first run of this instrument printed.
                if (!resynced) {
                    tsResyncs++;
                    resynced = true;
                }
                i++;
                continue;
            }
            resynced = false;
            int pid = ((data[i + 1] & 0x1F) << 8) | (data[i + 2] & 0xFF);
            tsPackets++;
            if (pid == 0x1FFF) {
                tsNulls++;
            }
            i += 188;
        }
    }

    /** TS packets delivered to the listener since construction (the driver's own count, not the host's). */
    public long tsPackets() {
        return tsPackets;
    }

    /** Null packets (PID 0x1FFF) among them: a mux at its rate carries padding, a receiver that over-counts may not. */
    public long tsNulls() {
        return tsNulls;
    }

    /** Times the reader had to resynchronise on the sync byte (a non-zero value means the seam was not aligned). */
    public long tsResyncs() {
        return tsResyncs;
    }

    public synchronized void stop() {
        running = false;
        generation++;
        synchronized (pipeLock) {
            cancelLocked();
        }
        Thread current = thread;
        if (current == Thread.currentThread()) {
            return; // called from the reader thread; let it exit on its own
        }
        thread = null;
        if (current == null) {
            return;
        }
        try {
            current.join(1500);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        if (current.isAlive()) {
            thread = current; // start() must not create a second reader
        }
    }

    /**
     * Re-arm after a tune or retune. If the host tunes while the reader is
     * running, call this before and after the tune, as the IT9308 integration
     * does; the timeout recovery would otherwise mask a stale queue.
     */
    public synchronized void restart() {
        stop();
        start();
    }

    public boolean isRunning() {
        return running;
    }

    /** "queued", "blocking" or "none" - for the host's log. */
    public String mode() {
        return mode;
    }

    // -- telemetry ----------------------------------------------------------

    public long completions() { return completions; }

    public long emptyCompletions() { return emptyCompletions; }

    public long shortCompletions() { return shortCompletions; }

    public long timeouts() { return timeouts; }

    public long errors() { return errors; }

    public long recoveries() { return recoveries; }

    /** Halt clears triggered by a long run of timeouts (suspect: a device that stopped). */
    public long timeoutRecoveries() { return timeoutRecoveries; }

    /** Halt clears triggered by a failed wait (suspect: a real endpoint halt). */
    public long errorRecoveries() { return errorRecoveries; }

    /** "request-wait" or "timeout-run": why the last halt clear happened. */
    public String lastRecoveryReason() { return lastRecoveryReason; }

    public long bytesRead() { return bytesRead; }

    /** Bytes not copied because the caller's buffer was smaller than the chunk. */
    public long droppedBytes() { return droppedBytes; }

    /** Bytes held from a chunk that did not fit the caller's buffer (handed out next). */
    public long carriedBytes() { return carriedBytes; }

    /** Requests currently armed on the endpoint: the pipeline depth. */
    public int inFlight() { return armed; }

    /** Completed chunks waiting for their turn in the ordered map. */
    public int readyDepth() {
        synchronized (pipeLock) {
            return ready.size();
        }
    }
}
