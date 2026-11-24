/*
 * Ported from OpenDTV (https://github.com/jpdcs/OpenDTV), MIT.
 * Copyright (c) 2026 jpdcs. The MIT permission notice is in NOTICE and LICENSE.
 */
package com.pbcnx.drivers.it9175;

/** Protocol core for ITE IT9175 dongles: firmware, init, tune, status. */
public final class It9175Device {
    /** Visible provenance marker: searchable attribution, not telemetry. */
    public static final String PROVENANCE = "it9175-pbcnx";

    /** Copyright (c) 2026 The IT9175 Open Driver Authors · MIT (see LICENSE). */
    private static final int LINK = 0;

    private final AfaIo io;
    private final Tuner tuner;

    public It9175Device(Transport transport) {
        this.io = new AfaIo(transport);
        this.tuner = new Tuner(io);
    }

    public byte[] readRegisters(int processor, long address, int count) {
        return io.read(processor, address, count);
    }

    public boolean writeRegisters(int processor, long address, byte[] data) {
        return io.write(processor, address, data);
    }

    public byte[] firmwareVersion(int processor) {
        return io.firmwareVersion(processor);
    }

    /** Uploads a 9,036-byte image using the chunk table, then starts it. */
    public boolean loadFirmware(byte[] image) {
        if (image == null || image.length != Firmware.SIZE) {
            return false;
        }
        if (!io.write(LINK, 0x4BFB, new byte[]{0})
                || !io.write(LINK, 0xCFFF, new byte[]{0})
                || !io.write(LINK, 0xF103, new byte[]{7})) {
            return false;
        }

        int offset = 0;
        for (int size : Firmware.CHUNKS) {
            byte[] chunk = new byte[size];
            System.arraycopy(image, offset, chunk, 0, size);
            offset += size;
            if (io.command(41, LINK, chunk, 0) == null) {
                return false;
            }
        }
        return io.command(35, LINK, null, 0) != null;
    }

    /** Reads the chip id and uploads firmware when the version is blank. */
    public String bringUp(byte[] image) {
        return bringUp(image, false);
    }

    /**
     * As {@link #bringUp(byte[])}; {@code cold} forces the upload even when the chip reports a
     * resident version. Mirrors {@code Device.init(cold=True)} in the Python driver.
     */
    public String bringUp(byte[] image, boolean cold) {
        byte[] identifier = readRegisters(LINK, 0x1222, 3);
        if (identifier == null) {
            throw new IllegalStateException("cannot read chip id");
        }
        int version = identifier[0] & 0xFF;
        int chip = (identifier[1] & 0xFF) | ((identifier[2] & 0xFF) << 8);

        byte[] firmware = firmwareVersion(LINK);
        if (firmware == null) {
            throw new IllegalStateException("no answer to the firmware version query");
        }
        boolean blank = true;
        for (byte value : firmware) {
            blank &= value == 0;
        }
        if (cold || blank) {
            if (!loadFirmware(image)) {
                throw new IllegalStateException("firmware image missing or wrong size");
            }
            firmware = firmwareVersion(LINK);
            if (firmware == null) {
                throw new IllegalStateException("firmware did not start");
            }
        }
        return "chip version=" + version + " id=0x" + Integer.toHexString(chip)
                + " firmware=" + toHex(firmware);
    }

    /**
     * Writes the pre-upload sequence: the closest the interface allows to the vendor's
     * {@code Cmd_reboot}.
     *
     * <p>Measured on hardware (2026-11-20): the writes stop the resident firmware and the device
     * re-enumerates, which kills this transport - so the caller must close it and re-open the
     * device before calling {@link #bringUp(byte[], boolean)}. The effect is state-dependent: one
     * run left the chip blank (needing the 9,036-byte upload), others showed no visible reset.</p>
     */
    public boolean forceBoot() {
        return io.write(LINK, 0x4BFB, new byte[]{0})
                && io.write(LINK, 0xCFFF, new byte[]{0})
                && io.write(LINK, 0xF103, new byte[]{7});
    }

    /**
     * Warm recovery with retries: bring the chip up and run the tuner scripts, repeat on failure.
     * Safe on a running chip - it never forces an upload. Mirrors {@code Device.recover()}.
     */
    public boolean recover(byte[] image, int attempts) {
        for (int attempt = 1; attempt <= Math.max(1, attempts); attempt++) {
            if (attempt > 1) {
                sleep(2000);
            }
            try {
                // Attempt 1 is warm. From attempt 2 the upload is forced: resident firmware does not
                // mean a running demod - the previous handle can leave the CPU suspended, and only
                // the upload restarts it (measured 2026-11-22: after a replug the warm path read
                // strength 100, snr 0.0 and never locked; a forced upload on the same handle locked
                // in 1224 ms).
                bringUp(image, attempt > 1);
                if (init()) {
                    return true;
                }
            } catch (RuntimeException error) {
                // the chip may still be returning from a previous session; retry
            }
        }
        return false;
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    public boolean init() {
        return tuner.init();
    }

    public boolean tune(int frequencyKhz) {
        return tuner.tune(frequencyKhz);
    }

    public boolean waitLock(boolean quick) {
        return tuner.waitLock(quick);
    }

    public boolean isLocked() {
        return tuner.mpeg2Locked();
    }

    public Status status() {
        return tuner.status();
    }

    /** The ISDB-T transmission parameters the demod reports (TMCC); readable before lock. */
    public Tmcc tmcc() {
        return tuner.tmcc();
    }

    /** A settled reading (two consecutive valid readings that agree); see {@link Tuner#tmccSettled}. */
    public Tmcc tmccSettled(int attempts, long delayMs) {
        return tuner.tmccSettled(attempts, delayMs);
    }

    private static String toHex(byte[] data) {
        StringBuilder builder = new StringBuilder();
        for (byte value : data) {
            builder.append(String.format("%02x ", value & 0xFF));
        }
        return builder.toString().trim();
    }
}
