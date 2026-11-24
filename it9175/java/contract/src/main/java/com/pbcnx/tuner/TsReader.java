package com.pbcnx.tuner;

/**
 * The stream seam: the host supplies the consumer, the package owns the endpoint.
 *
 * <p>Bytes arrive once {@code open()} armed the reader. No alignment is promised: the first batch after a
 * tune may start mid-packet, and the host finds the {@code 0x47} phase.
 */
public final class TsReader {

    private TsReader() {
    }

    /** The host's consumer. */
    public interface Listener {
        /** @param data the batch; only the first {@code length} bytes are valid */
        void onData(byte[] data, int length);
    }
}
