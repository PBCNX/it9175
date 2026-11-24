package com.pbcnx.tuner;

/** A scan's callbacks. The verdict is the stream, not the lock word: a scan reports what it saw. */
public interface ScanListener {

    /** One frequency visited. {@code status} is the snapshot taken there; {@code locked} its verdict. */
    void onFrequency(int frequencyKhz, boolean locked, TunerStatus status);

    /** The sweep finished: {@code found} frequencies locked out of {@code total}. */
    void onDone(int found, int total);
}
