package ph.pbcnx.it9175;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Dependency-free checks. The recording IO returns the same canned register
 * values as the Python generator, so the command list can be compared byte for
 * byte with the expected resource.
 */
public final class SelfTest {
    private SelfTest() {
    }

    private static final class RecordingIo implements Io {
        final List<String> writes = new ArrayList<>();
        final Map<String, Integer> canned = new HashMap<>();

        RecordingIo() {
            canned.put("8:ec86", 0);
            canned.put("8:ed03", 0);
            canned.put("8:1dc", 0);
            canned.put("8:1c6", 1);
            canned.put("8:ec4c", 0);
            canned.put("8:ed81", 16);
            canned.put("0:d8cf", 0);
            canned.put("8:f9f1", 1);
            canned.put("8:f9f2", 1);
            canned.put("8:f9f3", 1);
            canned.put("8:47", 1);
            canned.put("8:f5a9", 1);
            canned.put("8:13e", 50);
            canned.put("8:49", 50);
            canned.put("8:13f", 50);
            canned.put("8:1c9", 20);
        }

        public byte[] read(int processor, long address, int count) {
            if (processor == 0 && address == 0xD800) {
                return new byte[]{0};
            }
            if (processor == 8 && address == 0xED23) {
                return new byte[]{0x00, 0x10};
            }
            if (processor == 8 && address == 0x32) {
                return new byte[]{0, 0, 10, 0, 0, 100, 0};
            }
            Integer value = canned.get(processor + ":" + Long.toHexString(address));
            if (value != null) {
                return new byte[]{(byte) (int) value};
            }
            return new byte[count];
        }

        public boolean write(int processor, long address, byte[] data) {
            writes.add(processor + ":" + Long.toHexString(address) + ":" + toHex(data));
            return true;
        }

        public void sleep(int millis) {
        }

        public byte[] firmwareVersion(int processor) {
            return new byte[]{1, 0, 5, 5};
        }
    }

    public static void main(String[] args) throws Exception {
        frames();

        RecordingIo io = new RecordingIo();
        Tuner tuner = new Tuner(io);
        check(tuner.init(), "init");
        check(tuner.tune(599143), "tune 599143");
        check(tuner.tune(473143), "tune 473143");

        List<String> expected = readExpected();
        check(expected.size() == io.writes.size(),
                "write count " + io.writes.size() + " vs " + expected.size());
        for (int index = 0; index < expected.size(); index++) {
            check(expected.get(index).equals(io.writes.get(index)),
                    "line " + index + ": " + io.writes.get(index) + " != " + expected.get(index));
        }

        Status status = tuner.status();
        check(status.locked, "status locked");
        check(status.strengthPercent == 50, "strength " + status.strengthPercent);

        System.out.println("it9175 java self-test: OK (" + expected.size() + " commands)");
    }

    private static List<String> readExpected() throws Exception {
        InputStream stream = SelfTest.class.getResourceAsStream("/it9175/expected.txt");
        check(stream != null, "expected.txt missing");
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.isEmpty() && !line.startsWith("--")) {
                    lines.add(line);
                }
            }
        }
        return lines;
    }

    private static void frames() {
        byte[] read = AfaCmd.buildRead(0, AfaCmd.PROC_LINK, 0x1222, 1);
        check(toHex(read).equals("0b000000010200001222dbec"), "read frame " + toHex(read));

        byte[] write = AfaCmd.buildWrite(0, AfaCmd.PROC_OFDM, 0xEC4C, new byte[]{(byte) 0xA8});
        check(toHex(write).equals("0c80010001020000ec4ca83069"), "write frame " + toHex(write));

        byte[] command = AfaCmd.buildCommand(34, 0, 0, 0, new byte[]{1});
        check(toHex(command).equals("0600220001ffdc"), "command frame " + toHex(command));

        int total = 0;
        for (int chunk : Firmware.CHUNKS) {
            total += chunk;
        }
        check(total == Firmware.SIZE, "chunk total " + total);
        check(Firmware.CHUNKS.length == 189, "chunk count " + Firmware.CHUNKS.length);
    }

    private static String toHex(byte[] data) {
        StringBuilder builder = new StringBuilder();
        for (byte value : data) {
            builder.append(String.format("%02x", value & 0xFF));
        }
        return builder.toString();
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
