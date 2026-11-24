/*
 * Ported from OpenDTV (https://github.com/jpdcs/OpenDTV), MIT.
 * Copyright (c) 2026 jpdcs. The MIT permission notice is in NOTICE and LICENSE.
 */
package com.pbcnx.drivers.it9175;

/** Tuner status snapshot. */
public final class Status {
    public boolean locked;
    public int rawStrength = -1;
    public int strengthPercent = -1;
    public int rawQuality = -1;
    public int qualityPercent = -1;
    public int dbm = -1000;
    public int rawSnr = -1;
    public int snrDb = -1;
    public int berErrors = -1;
    public int berWindow = -1;
    public double ber = Double.NaN;

    @Override
    public String toString() {
        return "locked=" + locked + " strength=" + strengthPercent
                + " quality=" + qualityPercent + " dbm=" + dbm;
    }
}
