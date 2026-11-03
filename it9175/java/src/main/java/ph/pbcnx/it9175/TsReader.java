package ph.pbcnx.it9175;

/**
 * Blocking reader for the MPEG-TS endpoint ({@code 0x84}).
 *
 * The host owns the thread and the buffering; this is the seam an Android USB
 * host, a BonDriver ring, or a test fills.
 *
 * The first read after a tune may start in the middle of a packet: the
 * demodulator does not align its first bulk transfer. Callers that need whole
 * packets should lock onto the {@code 0x47} phase themselves; the Python
 * driver's {@code It9175Device._align_ts} is the reference implementation.
 */
public interface TsReader {
    /**
     * Read one batch.
     *
     * @return bytes read (1..dst.length), or -1 on timeout/error
     */
    int read(byte[] dst, int timeoutMs);
}
