package ph.pbcnx.it9175.demo;

import java.io.IOException;
import java.io.OutputStream;

/**
 * Locks onto the 188-byte packet phase and writes whole packets.
 *
 * The first bulk read after a tune can start mid-packet, so the app, not the
 * core, owns alignment (the Python reference is It9175Device._align_ts).
 */
final class TsAligner {
    private final byte[] buffer = new byte[65536];
    private int length;

    int write(byte[] data, int count, OutputStream out) throws IOException {
        if (count <= 0) {
            return 0;
        }
        if (length + count > buffer.length) {
            int keep = Math.min(length, 188);
            System.arraycopy(buffer, length - keep, buffer, 0, keep);
            length = keep;
        }
        System.arraycopy(data, 0, buffer, length, count);
        length += count;

        int phase = -1;
        int probes = Math.min(188, length - 188);
        for (int i = 0; i < probes; i++) {
            if (buffer[i] == 0x47 && (length < i + 376 || buffer[i + 188] == 0x47)) {
                phase = i;
                break;
            }
        }
        if (phase < 0) {
            if (length > 376) {
                System.arraycopy(buffer, length - 188, buffer, 0, 188);
                length = 188;
            }
            return 0;
        }

        int written = 0;
        int pos = phase;
        while (length - pos >= 188) {
            out.write(buffer, pos, 188);
            pos += 188;
            written++;
        }
        int rest = length - pos;
        if (rest > 0) {
            System.arraycopy(buffer, pos, buffer, 0, rest);
        }
        length = rest;
        return written;
    }
}
