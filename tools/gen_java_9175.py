"""Emit Java tables and the expected init/tune command list for the port tests."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from it9175 import tables
from it9175.tuner import Tuner

JAVA = os.path.join(ROOT, "it9175", "java", "src", "main", "java", "ph", "pbcnx", "it9175")
TEST = os.path.join(ROOT, "it9175", "java", "src", "test", "resources", "it9175")


def java_array(name, values):
    lines = []
    for index in range(0, len(values), 8):
        chunk = ", ".join('"{}"'.format(value) for value in values[index:index + 8])
        lines.append("            " + chunk + ",")
    return "    public static final String[] %s = {\n%s\n    };\n" % (name, "\n".join(lines))


def java_bands(name, rows):
    lines = []
    for row in rows:
        lines.append("            {" + ", ".join(str(value) for value in row) + "},")
    return "    public static final int[][] %s = {\n%s\n    };\n" % (name, "\n".join(lines))


source = ["package ph.pbcnx.it9175;", "", "/** Script tables and band rows, generated from the Python tables. */",
          "public final class Tables {", "    private Tables() {", "    }", ""]
for name in ("INIT_A0", "INIT_A1", "INIT_B0", "INIT_B1", "TUNE_PRE0", "TUNE_PRE1"):
    source.append(java_array(name, list(getattr(tables, name))))
for name in ("BANDS0", "BANDS1"):
    source.append(java_bands(name, [list(row) for row in getattr(tables, name)]))
source.append("}")

os.makedirs(JAVA, exist_ok=True)
with open(os.path.join(JAVA, "Tables.java"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(source))


class FakeIo:
    def __init__(self):
        self.log = []

    def read(self, proc, addr, count):
        if proc == 0 and addr == 0xD800:
            return bytes([0])
        if proc == 8 and addr == 0xED23:
            return bytes([0x00, 0x10])
        if proc == 8 and addr == 0x32:
            return bytes([0, 0, 10, 0, 0, 100, 0])
        canned = {
            (8, 0xEC86): 0, (8, 0xED03): 0, (8, 0x1DC): 0, (8, 0x1C6): 1,
            (8, 0xEC4C): 0, (8, 0xED81): 16, (0, 0xD8CF): 0,
            (8, 0xF9F1): 1, (8, 0xF9F2): 1, (8, 0xF9F3): 1, (8, 0x47): 1,
            (8, 0xF5A9): 1, (8, 0x13E): 50, (8, 0x49): 50, (8, 0x13F): 50,
            (8, 0x1C9): 20,
        }
        if (proc, addr) in canned:
            return bytes([canned[(proc, addr)]])
        return bytes(count)

    def write(self, proc, addr, data):
        self.log.append("%d:%x:%s" % (proc, addr, bytes(data).hex()))
        return True

    def sleep(self, ms):
        pass

    def fw_version(self, proc):
        return bytes([1, 0, 5, 5])


def run(tuner, io, label):
    io.log.append("--" + label)
    tuner.init()
    tuner.tune(599143)
    tuner.tune(473143)
    return io.log


io = FakeIo()
tuner = Tuner(io)
lines = run(tuner, io, "init")
os.makedirs(TEST, exist_ok=True)
with open(os.path.join(TEST, "expected.txt"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(lines) + "\n")
print("tables + expected written;", len(lines), "lines,", len(tables.INIT_A0), "init ops")
