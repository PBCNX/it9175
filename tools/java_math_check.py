"""Build a small Java harness around OpenDTV's It9175Tuner to compare the
Python port's tuning maths against the original implementation."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get(
    "OPENDTV_SOURCE",
    os.path.join(os.path.dirname(ROOT), "OpenDTVmod", "windows-driver",
                 "it9175", "src", "ph", "opendtv", "source"))
JDK = os.environ.get(
    "JDK_BIN",
    os.path.join(os.path.dirname(ROOT), "OpenDTVmod", "tools", "jdk17", "bin"))
WORK = os.path.join(ROOT, ".tmp", "javacheck")

STUBS = {
    "androidx/core/location/LocationRequestCompat.java":
        "package androidx.core.location;\npublic class LocationRequestCompat { public static final int QUALITY_LOW_POWER = 104; }\n",
    "androidx/media3/extractor/MpegAudioUtil.java":
        "package androidx.media3.extractor;\npublic class MpegAudioUtil { public static final int MAX_RATE_BYTES_PER_SECOND = 40000; }\n",
    "androidx/media3/extractor/ts/PsExtractor.java":
        "package androidx.media3.extractor.ts;\npublic class PsExtractor { public static final int VIDEO_STREAM_MASK = 240; }\n",
    "androidx/media3/exoplayer/ExoPlayer.java":
        "package androidx.media3.exoplayer;\npublic class ExoPlayer { public static final long DEFAULT_DETACH_SURFACE_TIMEOUT_MS = 2000; }\n",
    "androidx/media3/exoplayer/Renderer.java":
        "package androidx.media3.exoplayer;\npublic class Renderer { public static final long DEFAULT_DURATION_TO_PROGRESS_US = 10000; }\n",
    "ph/opendtv/source/Harness.java": r"""
package ph.opendtv.source;

public final class Harness {
    static final class Io implements It9175Tuner.Io {
        final java.util.HashMap<Long, Integer> regs = new java.util.HashMap<>();
        long key(int proc, long addr) { return ((long) proc << 32) | (addr & 0xFFFFFFFFL); }
        public byte[] read(int proc, long addr, int n) {
            byte[] b = new byte[n];
            for (int i = 0; i < n; i++) {
                Integer v = regs.get(key(proc, addr + i));
                b[i] = (byte) (v == null ? 0 : v);
            }
            return b;
        }
        public boolean write(int proc, long addr, byte[] d) {
            for (int i = 0; i < d.length; i++) regs.put(key(proc, addr + i), d[i] & 255);
            return true;
        }
        public boolean fwVersion(int proc) { return true; }
        public void sleep(int ms) { }
    }

    public static void main(String[] args) {
        Io io = new Io();
        io.regs.put(io.key(0, 0xD800), 0x00);
        io.regs.put(io.key(8, 0xEC86), 0);
        io.regs.put(io.key(8, 0xED03), 3);
        io.regs.put(io.key(8, 0xED23), 0x22);
        io.regs.put(io.key(8, 0xED24), 0x12);
        io.regs.put(io.key(8, 0x1C6), 1);
        io.regs.put(io.key(8, 0x1DC), 0);
        StringBuilder log = new StringBuilder();
        It9175Tuner t = new It9175Tuner(io, log);
        boolean ok = t.init();
        System.out.println("init " + ok);
        System.out.println(t.describe());
        long[] freqs = {473143, 497143, 599143, 671143, 695143};
        for (long f : freqs) {
            long[] r = t.freqCode(f);
            System.out.printf("%d nc=%d nv=%d fcw=%d lo=%d iq=%d%n",
                f, r[0], r[1], r[2], t.loFreq(f), t.calFreqIqik(f, 16));
        }
    }
}
""",
}


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    for rel, text in STUBS.items():
        path = os.path.join(WORK, "src", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    for name in ("It9175Tuner.java", "It9175Data.java", "SignalStatus.java"):
        shutil.copy(os.path.join(SRC, name), os.path.join(WORK, "src", "ph", "opendtv", "source", name))
    sources = []
    for base, _dirs, files in os.walk(os.path.join(WORK, "src")):
        sources += [os.path.join(base, f) for f in files if f.endswith(".java")]
    os.makedirs(os.path.join(WORK, "classes"), exist_ok=True)
    subprocess.run([os.path.join(JDK, "javac.exe"), "-encoding", "UTF-8", "-d",
                    os.path.join(WORK, "classes")] + sources, check=True)
    out = subprocess.run([os.path.join(JDK, "java.exe"), "-cp",
                          os.path.join(WORK, "classes"), "ph.opendtv.source.Harness"],
                         check=True, capture_output=True, text=True)
    print(out.stdout)


if __name__ == "__main__":
    main()
