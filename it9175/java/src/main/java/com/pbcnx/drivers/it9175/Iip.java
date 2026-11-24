package com.pbcnx.drivers.it9175;

/**
 * IIP: the ISDB-T Information Packet (PID {@code 0x1FF0}), the frame-ahead transmission-control
 * packet.
 *
 * <p>One TSP per multiplex frame, carried in the invalid hierarchy rather than in a layer. Its
 * payload describes the multiplex frame <b>after</b> the one carrying it: mode and guard interval
 * (an independent confirmation of the demod's TMCC words), the current and next layer
 * configurations, and the <b>B26 (EWBS) copy for the next frame</b> - so a receiver whose demod
 * exposes no activation bit can still see the alarm, including the flag-only case where the PMT
 * carries no {@code 0xFC} descriptor.</p>
 *
 * <p>Layout per ARIB STD-B31 v2.2-E1 Tables 5-8/5-10, ported from this project's Python decoder
 * ({@code it9175/iip.py}), which was ported from IT9308's. Validated here against two real
 * payloads from the EWBS Test Streams capture (ewbs 0 and 1) and against the family's shared
 * 188-byte fixture.</p>
 *
 * <p>{@code CRC_32} is ISO/IEC 13818-1 (poly {@code 0x04C11DB7}, init {@code 0xFFFFFFFF}, no
 * reflection, no final XOR) over the first 128 bits of the 160-bit MCCI, stored big-endian in the
 * last four. A caller that shows an alert should check {@link #crcOk}: a corrupt packet must never
 * become one.</p>
 */
public final class Iip {

    /** The TSP PID the IIP is carried on. */
    public static final int PID = 0x1FF0;

    public static final String UNKNOWN = "?";
    private static final int UNUSED = 7;

    private static final String[] MODES = {null, "2K", "4K", "8K"};
    private static final String[] GUARDS = {"1/32", "1/16", "1/8", "1/4"};
    private static final String[] MODULATIONS = {"DQPSK", "QPSK", "16QAM", "64QAM"};
    private static final String[] CODE_RATES = {"1/2", "2/3", "3/4", "5/6", "7/8"};
    private static final String[] INTERLEAVES = {"I0", "I1", "I2", "I4"};

    /** One layer of the current frame; {@code present} is false for an unused layer. */
    public static final class Layer {
        public final boolean present;
        public final String modulation;
        public final String codeRate;
        public final String interleave;
        public final int segments;

        private Layer() {
            this(false, UNKNOWN, UNKNOWN, UNKNOWN, 0);
        }

        private Layer(boolean present, String modulation, String codeRate, String interleave,
                      int segments) {
            this.present = present;
            this.modulation = modulation;
            this.codeRate = codeRate;
            this.interleave = interleave;
            this.segments = segments;
        }

        @Override
        public String toString() {
            if (!present) {
                return "-";
            }
            return modulation + " " + codeRate + " " + interleave + " " + segments + "seg";
        }
    }

    public final int pointer;
    public final String mode;
    public final String guard;
    public final String nextMode;
    public final String nextGuard;
    public final boolean ewbs;
    public final boolean partial;
    public final Layer layerA;
    public final Layer layerB;
    public final Layer layerC;
    public final int branch;
    public final int lastBranch;
    public final int netSyncLength;
    public final boolean crcOk;

    private Iip(int pointer, String mode, String guard, String nextMode, String nextGuard,
                boolean ewbs, boolean partial, Layer layerA, Layer layerB, Layer layerC,
                int branch, int lastBranch, int netSyncLength, boolean crcOk) {
        this.pointer = pointer;
        this.mode = mode;
        this.guard = guard;
        this.nextMode = nextMode;
        this.nextGuard = nextGuard;
        this.ewbs = ewbs;
        this.partial = partial;
        this.layerA = layerA;
        this.layerB = layerB;
        this.layerC = layerC;
        this.branch = branch;
        this.lastBranch = lastBranch;
        this.netSyncLength = netSyncLength;
        this.crcOk = crcOk;
    }

    /** Total segments across the three current layers. */
    public int segments() {
        return layerA.segments + layerB.segments + layerC.segments;
    }

    /** Decode one IIP payload: the bytes after the 4-byte TSP header (184 in the standard). */
    public static Iip decode(byte[] payload) {
        if (payload == null || payload.length < 25) {
            throw new IllegalArgumentException("IIP payload too short: "
                    + (payload == null ? 0 : payload.length) + " bytes");
        }
        int pointer = ((payload[0] & 0xFF) << 8) | (payload[1] & 0xFF);
        BitReader reader = new BitReader(payload, 2, 20);          // the 160-bit MCCI block
        reader.take(1);                                           // TMCC synchronization word
        reader.take(1);                                           // AC data effective position
        reader.take(2);                                           // reserved
        reader.take(4);                                           // initialization timing indicator
        String mode = lookup(MODES, reader.take(2));
        String guard = lookup(GUARDS, reader.take(2));
        String nextMode = lookup(MODES, reader.take(2));
        String nextGuard = lookup(GUARDS, reader.take(2));
        reader.take(2);                                           // system identifier
        reader.take(4);                                           // count down index
        boolean ewbs = reader.take(1) != 0;                       // B26 copy for the next frame
        boolean partial = reader.take(1) != 0;
        Layer layerA = layer(reader);
        Layer layerB = layer(reader);
        Layer layerC = layer(reader);
        reader.take(1);                                           // next partial reception flag
        layer(reader);                                            // next-frame layers
        layer(reader);
        layer(reader);
        reader.take(3 + 12 + 10);                                 // phase, reserved, reserved

        byte[] mcci = new byte[20];
        System.arraycopy(payload, 2, mcci, 0, 20);
        boolean crcOk = crc32Mpeg2(mcci, 16) == readInt(mcci, 16);
        return new Iip(pointer, mode, guard, nextMode, nextGuard, ewbs, partial,
                layerA, layerB, layerC, payload[22] & 0xFF, payload[23] & 0xFF,
                payload[24] & 0xFF, crcOk);
    }

    private static Layer layer(BitReader reader) {
        int modulation = reader.take(3);
        int code = reader.take(3);
        int interleave = reader.take(3);
        int segments = reader.take(4);
        boolean present = modulation != UNUSED && segments != 15;
        if (!present) {
            return new Layer();
        }
        return new Layer(true, lookup(MODULATIONS, modulation), lookup(CODE_RATES, code),
                lookup(INTERLEAVES, interleave), segments);
    }

    private static String lookup(String[] table, int index) {
        return index >= 0 && index < table.length && table[index] != null ? table[index] : UNKNOWN;
    }

    /**
     * ISO/IEC 13818-1 CRC-32 (STD-B31 Table 5-10 {@code CRC_32}) over the first {@code length}
     * bytes: poly {@code 0x04C11DB7}, init {@code 0xFFFFFFFF}, no reflection, no final XOR.
     */
    public static int crc32Mpeg2(byte[] data, int length) {
        int crc = 0xFFFFFFFF;
        for (int index = 0; index < length; index++) {
            crc ^= (data[index] & 0xFF) << 24;
            for (int bit = 0; bit < 8; bit++) {
                if ((crc & 0x80000000) != 0) {
                    crc = (crc << 1) ^ 0x04C11DB7;
                } else {
                    crc = crc << 1;
                }
            }
        }
        return crc;
    }

    private static int readInt(byte[] data, int offset) {
        return ((data[offset] & 0xFF) << 24) | ((data[offset + 1] & 0xFF) << 16)
                | ((data[offset + 2] & 0xFF) << 8) | (data[offset + 3] & 0xFF);
    }

    /** Big-endian bit reader over a byte range; the IIP is defined as a bit string. */
    private static final class BitReader {
        private final byte[] data;
        private int bit;

        BitReader(byte[] data, int offset, int length) {
            this.data = new byte[length];
            System.arraycopy(data, offset, this.data, 0, length);
        }

        int take(int count) {
            int value = 0;
            for (int index = 0; index < count; index++) {
                int byteIndex = bit >> 3;
                int shift = 7 - (bit & 7);
                value = (value << 1) | ((data[byteIndex] >> shift) & 1);
                bit++;
            }
            return value;
        }
    }

    @Override
    public String toString() {
        return "iip mode " + mode + " guard " + guard + " partial " + (partial ? 1 : 0)
                + " ewbs " + (ewbs ? 1 : 0) + " L0:" + layerA + " L1:" + layerB + " L2:" + layerC
                + " next " + nextMode + "/" + nextGuard + " crc " + (crcOk ? "ok" : "FAIL");
    }
}
