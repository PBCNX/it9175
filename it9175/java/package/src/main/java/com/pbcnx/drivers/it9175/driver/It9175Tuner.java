package com.pbcnx.drivers.it9175.driver;

import android.content.Context;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;

import java.io.IOException;

import com.pbcnx.drivers.it9175.Status;
import com.pbcnx.drivers.it9175.Tmcc;
import com.pbcnx.drivers.it9175.android.TunerSession;
import com.pbcnx.tuner.ScanListener;
import com.pbcnx.tuner.Tuner;
import com.pbcnx.tuner.TunerException;
import com.pbcnx.tuner.TunerStatus;
import com.pbcnx.tuner.TsReader;

/** The door implemented over {@link TunerSession}: mapping only, no protocol of its own. */
final class It9175Tuner implements Tuner {

    /** Canonical mode: 0 = 2K, 1 = 4K, 2 = 8K. This chip's register order is 0 = 2K, 1 = 8K, 2 = 4K. */
    private static final int[] MODE_CANONICAL = {0, 2, 1};

    /** The chip's modulation naming, in the canonical index order (DQPSK, QPSK, 16QAM, 64QAM). */
    private static final String[] MODULATIONS = {"DQPSK", "QPSK", "16QAM", "64QAM"};
    private static final String[] CODE_RATES = {"1/2", "2/3", "3/4", "5/6", "7/8"};
    private static final int[] INTERLEAVE_INDEX = {0, 1, 2, 4};

    private final TunerSession session;

    /** True once this handle has healed itself; a second attempt would be a reset loop, not a recovery. */
    private boolean healedOnFirstTune;

    It9175Tuner(Context context, UsbDevice device, byte[] firmware, TsReader.Listener listener) {
        UsbManager manager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
        this.session = new TunerSession(manager, device, firmware, new Sink(listener));
    }

    /** Bridges the contract's listener to the adapter's. */
    private static final class Sink implements com.pbcnx.drivers.it9175.android.AndroidTsReader.Listener {
        private final TsReader.Listener listener;

        Sink(TsReader.Listener listener) {
            this.listener = listener;
        }

        @Override
        public void onData(byte[] data, int length) {
            if (listener != null) {
                listener.onData(data, length);
            }
        }
    }

    @Override
    public void open() throws TunerException {
        try {
            session.open();
        } catch (IOException error) {
            throw new TunerException("open failed: " + error.getMessage(), error);
        }
    }

    /**
     * Tune, and heal the one state this package can recognise on its own.
     *
     * <p>A new USB handle does not mean a running demod: the part can come back reporting a resident firmware
     * version and a strong signal while the CPU is still suspended from the previous handle, and a warm bring-up
     * then never locks (`strength 100, snr 0.0, lock false`, measured on a host with three replugs, 2026-11-22).
     * When that signature appears on the FIRST tune after open, this heals it the only way that works - a forced
     * upload, which restarts the CPU - and retries once.
     *
     * <p>It is deliberately narrow: only the first tune, only when the frontend reports signal, and only once per
     * handle. A genuinely dead channel has no strength and is left alone; a second failure is a verdict, not a loop.
     */
    @Override
    public boolean tune(int frequencyKhz) {
        // A tune goes through zap(), not through the session's plain tune(): the reader must be re-armed around
        // the tune, or a host that tunes once and expects bytes gets a locked demod with a dead pipe. Measured on
        // Measured in the host app (2026-11-22): first tune via tune() -> lock true, 0 KiB for ten seconds, twice; the same tune
        // via zap() -> 1,273 KiB in the first 5 s window. The contract's zap is "stop, tune, wait, re-arm" and the
        // first tune has no reason to be the exception.
        boolean locked = session.zap(frequencyKhz);
        if (locked || healedOnFirstTune) {
            return locked;
        }
        TunerStatus status = status();
        if (status == null || status.strengthPercent <= 0) {
            return false;                      // no signal to explain: the channel, not the demod
        }
        healedOnFirstTune = true;
        if (session.recover()) {               // forces the upload from its second attempt
            return session.zap(frequencyKhz);
        }
        return false;
    }

    @Override
    public boolean zap(int frequencyKhz) {
        return session.zap(frequencyKhz);
    }

    /** True when this handle has already healed itself once (for a host's log). */
    public boolean healedOnFirstTune() {
        return healedOnFirstTune;
    }

    @Override
    public TunerStatus status() {
        Status status = session.status();
        if (status == null) {
            return new TunerStatus(false, -1, -1, -1);
        }
        return new TunerStatus(status.locked, status.strengthPercent, status.qualityPercent, status.snrDb);
    }

    @Override
    public com.pbcnx.tuner.Tmcc tmcc() {
        return map(session.core() == null ? null : session.core().tmcc());
    }

    @Override
    public com.pbcnx.tuner.Tmcc tmccSettled(int attempts, long delayMs) {
        return map(session.core() == null ? null : session.core().tmccSettled(attempts, delayMs));
    }

    @Override
    public boolean recover() {
        return session.recover();
    }

    @Override
    public void suspend() {
        session.suspend();
    }

    @Override
    public boolean resume(UsbDevice device) throws TunerException {
        try {
            return session.resume(device);
        } catch (IOException error) {
            throw new TunerException("resume failed: " + error.getMessage(), error);
        }
    }

    @Override
    public void scan(int startKhz, int stopKhz, int stepKhz, int seconds, ScanListener listener) {
        final int from = Math.min(startKhz, stopKhz);
        final int to = Math.max(startKhz, stopKhz);
        final int step = Math.max(1, stepKhz);
        Thread worker = new Thread(() -> {
            int found = 0;
            int total = 0;
            for (int frequency = from; frequency <= to; frequency += step) {
                total++;
                boolean locked = session.tune(frequency);
                if (locked) {
                    found++;
                }
                if (listener != null) {
                    listener.onFrequency(frequency, locked, status());
                }
            }
            if (listener != null) {
                listener.onDone(found, total);
            }
        }, "it9175-scan");
        worker.setDaemon(true);
        worker.start();
    }

    @Override
    public void close() {
        session.close();
    }

    /** Maps the core record to the canonical one; null in, null out. */
    private static com.pbcnx.tuner.Tmcc map(Tmcc reading) {
        if (reading == null) {
            return null;
        }
        int mode = indexOfMode(reading.mode);
        int guard = indexOfGuard(reading.guard);
        com.pbcnx.tuner.Tmcc.Layer[] layers = new com.pbcnx.tuner.Tmcc.Layer[3];
        for (int i = 0; i < layers.length; i++) {
            Tmcc.Layer layer = reading.layers != null && i < reading.layers.length ? reading.layers[i] : null;
            layers[i] = layer == null
                    ? new com.pbcnx.tuner.Tmcc.Layer(0, 0, -1, 0)
                    : new com.pbcnx.tuner.Tmcc.Layer(layer.segments,
                            indexOf(MODULATIONS, layer.modulation),
                            indexOf(CODE_RATES, layer.codeRate),
                            indexOfInterleave(layer.interleave));
        }
        // This chip exposes no EWBS flag (five methods, full byte space): -1 is a value, not a gap.
        return new com.pbcnx.tuner.Tmcc(mode, guard, reading.partial, -1, layers);
    }

    private static int indexOfMode(String mode) {
        if ("2K".equals(mode)) {
            return MODE_CANONICAL[0];
        }
        if ("8K".equals(mode)) {
            return MODE_CANONICAL[1];
        }
        if ("4K".equals(mode)) {
            return MODE_CANONICAL[2];
        }
        return -1;
    }

    private static int indexOfGuard(String guard) {
        if ("1/32".equals(guard)) {
            return 0;
        }
        if ("1/16".equals(guard)) {
            return 1;
        }
        if ("1/8".equals(guard)) {
            return 2;
        }
        if ("1/4".equals(guard)) {
            return 3;
        }
        return -1;
    }

    private static int indexOf(String[] table, String value) {
        for (int i = 0; i < table.length; i++) {
            if (table[i].equals(value)) {
                return i;
            }
        }
        return -1;
    }

    private static int indexOfInterleave(int depth) {
        for (int i = 0; i < INTERLEAVE_INDEX.length; i++) {
            if (INTERLEAVE_INDEX[i] == depth) {
                return i;
            }
        }
        return -1;
    }
}
