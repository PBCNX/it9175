package com.pbcnx.tuner;

/** A signal snapshot. Every unread field is -1, never 0 and never a guess. */
public final class TunerStatus {

    public final boolean locked;
    public final int strengthPercent;
    public final int qualityPercent;
    public final int snrDb;

    public TunerStatus(boolean locked, int strengthPercent, int qualityPercent, int snrDb) {
        this.locked = locked;
        this.strengthPercent = strengthPercent;
        this.qualityPercent = qualityPercent;
        this.snrDb = snrDb;
    }

    @Override
    public String toString() {
        return "locked=" + locked + " strength=" + strengthPercent
                + " quality=" + qualityPercent + " snr=" + snrDb;
    }
}
