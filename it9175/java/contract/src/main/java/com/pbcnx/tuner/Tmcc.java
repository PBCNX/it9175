package com.pbcnx.tuner;

/**
 * The transmission parameters, canonical across the family.
 *
 * <pre>
 *   mode        0 = 2K, 1 = 4K, 2 = 8K      (a package translates its own numbering; the 9175's register
 *                                            order is 0 = 2K, 1 = 8K, 2 = 4K - 1 and 2 swap)
 *   guard       0 = 1/32, 1 = 1/16, 2 = 1/8, 3 = 1/4
 *   partial     true when partial reception is announced
 *   ewbs        THREE-STATE int: 1 announces, 0 does not, -1 this part cannot say. Never a boolean.
 *   layers[3]   segments, modulation 0..3, codeRate 0..4 or -1, interleaving 0..3 (an INDEX: 3 = I4)
 * </pre>
 */
public final class Tmcc {

    /** One layer; {@code segments == 0} means absent. */
    public static final class Layer {
        public final int segments;
        public final int modulation;
        public final int codeRate;
        public final int interleaving;

        public Layer(int segments, int modulation, int codeRate, int interleaving) {
            this.segments = segments;
            this.modulation = modulation;
            this.codeRate = codeRate;
            this.interleaving = interleaving;
        }
    }

    public final int mode;
    public final int guard;
    public final boolean partial;
    public final int ewbs;
    public final Layer[] layers;

    public Tmcc(int mode, int guard, boolean partial, int ewbs, Layer[] layers) {
        this.mode = mode;
        this.guard = guard;
        this.partial = partial;
        this.ewbs = ewbs;
        this.layers = layers;
    }

    /** Total segments claimed by present layers. */
    public int segments() {
        int total = 0;
        for (Layer layer : layers) {
            total += layer.segments;
        }
        return total;
    }

    /**
     * A reading is a channel only when 1..13 segments are claimed by present layers.
     *
     * <p>Mode and guard are NOT required: on a part where they ride in the IIP (or are absent by design) they read
     * -1, and requiring them made every reading through this door invalid on that part (TUNER-CONTRACT 1.2, §4.8,
     * forced by LME2510; raised against the adopted artefact on 2026-11-22).
     *
     * <p>The segment rule is what keeps the zero trap closed: an undecoded block reads all-zero and claims no
     * segments, so it is still invalid - the corroboration is the segments, not the label.
     */
    public boolean valid() {
        return segments() >= 1 && segments() <= 13;
    }

    @Override
    public String toString() {
        return "mode " + mode + " guard " + guard + " partial " + (partial ? 1 : 0)
                + " ewbs " + ewbs + " segments " + segments();
    }
}
