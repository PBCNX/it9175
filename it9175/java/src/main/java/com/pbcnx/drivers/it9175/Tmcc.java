package com.pbcnx.drivers.it9175;

/**
 * The ISDB-T transmission parameters (TMCC), as the IT9175's demod reports them.
 *
 * <p>The demod decodes the TMCC signal itself and publishes mode, guard interval,
 * partial reception and the three layers in eight registers on the OFDM processor.
 * The field map was found with a controlled mux (DekTec DTA-115, one parameter
 * changed per run) and validated against the EWBS Test Streams broadcast capture:
 *
 * <pre>
 *   0xF900  mode (bits 15:8: 0=2K, 1=8K, 2=4K) + guard (bits 7:0: 0=1/32,1=1/16,2=1/8,3=1/4)
 *   0xF902  partial reception (bit 8) + layer A modulation (bits 1:0)
 *   0xF904  layer A code rate (bits 15:8) + layer A interleave (bits 1:0)
 *   0xF906  layer A segments (bits 15:8) + layer B modulation (bits 1:0)
 *   0xF908  layer B code rate (bits 15:8) + layer B interleave (bits 1:0)
 *   0xF90A  layer B segments (bits 15:8) + layer C modulation (bits 1:0)
 *   0xF90C  layer C code rate (bits 15:8) + layer C interleave (bits 1:0)
 *   0xF90E  layer C segments (bits 15:8)
 * </pre>
 *
 * <p>Readable before lock: the parameters are available as soon as the demod
 * decodes the TMCC, without waiting for the transport stream to lock.
 */
public final class Tmcc {

    /** Registers read from the OFDM processor, in decode order. */
    public static final int[] REGISTERS = {
            0xF900, 0xF902, 0xF904, 0xF906, 0xF908, 0xF90A, 0xF90C, 0xF90E};

    private static final String[] MODES = {"2K", "8K", "4K"};
    private static final String[] GUARDS = {"1/32", "1/16", "1/8", "1/4"};
    private static final String[] MODULATIONS = {"DQPSK", "QPSK", "16QAM", "64QAM"};
    private static final String[] CODE_RATES = {"1/2", "2/3", "3/4", "5/6", "7/8"};
    private static final int[] INTERLEAVES = {0, 1, 2, 4};
    private static final int NO_LAYER = 0x0F;
    private static final int NO_MODULATION = 0x07;

    /** One layer of the channel. */
    public static final class Layer {
        public final int segments;
        public final String modulation;
        public final String codeRate;
        /** Time interleave as it is on air: 0, 1, 2 or 4; -1 when the layer is unused. */
        public final int interleave;

        Layer(int segments, String modulation, String codeRate, int interleave) {
            this.segments = segments;
            this.modulation = modulation;
            this.codeRate = codeRate;
            this.interleave = interleave;
        }

        @Override
        public String toString() {
            if (segments == 0) {
                return "-";
            }
            return modulation + " " + segments + "seg code " + codeRate + " I" + interleave;
        }
    }

    public final String mode;
    public final String guard;
    public final boolean partial;
    public final Layer[] layers;

    private Tmcc(String mode, String guard, boolean partial, Layer[] layers) {
        this.mode = mode;
        this.guard = guard;
        this.partial = partial;
        this.layers = layers;
    }

    /** Total segments across the layers. */
    public int segments() {
        int total = 0;
        for (Layer layer : layers) {
            total += layer.segments;
        }
        return total;
    }

    /** True when the fields describe a real ISDB-T channel. */
    public boolean valid() {
        return mode != null && guard != null && segments() >= 1 && segments() <= 13;
    }

    private static String pick(String[] table, int index) {
        return index >= 0 && index < table.length ? table[index] : null;
    }

    private static int segmentsOf(int word) {
        int high = (word >> 8) & 0xFF;
        return high == NO_LAYER ? 0 : high;
    }

    private static String modulationOf(int word, int shift) {
        int code = (word >> shift) & 0x07;
        return code == NO_MODULATION ? null : pick(MODULATIONS, code & 0x03);
    }

    private static Layer layer(int segments, String modulation, int control, int segmentsWord) {
        if (segments == 0) {
            return new Layer(0, null, null, -1);
        }
        String codeRate = pick(CODE_RATES, (control >> 8) & 0x07);
        int interleave = INTERLEAVES[control & 0x03];
        return new Layer(segments, modulation, codeRate, interleave);
    }

    /** Build a TMCC record from the eight register values, in {@link #REGISTERS} order. */
    public static Tmcc decode(int[] words) {
        int[] w = new int[REGISTERS.length];
        for (int i = 0; i < REGISTERS.length; i++) {
            w[i] = i < words.length ? words[i] : 0;
        }
        String mode = pick(MODES, (w[0] >> 8) & 0x03);
        String guard = pick(GUARDS, w[0] & 0x03);
        boolean partial = ((w[1] >> 8) & 0x01) != 0;
        Layer a = layer(segmentsOf(w[3]), modulationOf(w[1], 0), w[2], w[3]);
        Layer b = layer(segmentsOf(w[5]), modulationOf(w[3], 0), w[4], w[5]);
        Layer c = layer(segmentsOf(w[7]), modulationOf(w[5], 0), w[6], w[7]);
        return new Tmcc(mode, guard, partial, new Layer[]{a, b, c});
    }

    @Override
    public String toString() {
        StringBuilder text = new StringBuilder();
        text.append("mode ").append(mode == null ? "?" : mode)
            .append(" guard ").append(guard == null ? "?" : guard)
            .append(" partial ").append(partial ? 1 : 0);
        for (int i = 0; i < layers.length; i++) {
            text.append(" L").append(i).append(':').append(layers[i]);
        }
        return text.toString();
    }
}
