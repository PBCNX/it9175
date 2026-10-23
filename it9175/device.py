"""Transport and device logic for the IT9175 dongle (ITE IT9175, 048d:275a).

The USB layer is deliberately small and replaceable: UsbBackend talks to a real
device through libusb, SimBackend is a register-level fake used by the tests and
by `it9175 sim`.
"""
import os
import time

from . import afa
from .tuner import Tuner

VID = 0x048D
PID_IT9175 = 0x275A
PID_IT9308 = 0x9308
PID_IT9309 = 0x9309

EP_CMD_OUT = 0x02
EP_CMD_IN = 0x81
EP_TS_IN = 0x84

TS_READ_SIZE = 16356


class UsbError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Real USB backend
# ---------------------------------------------------------------------------

def _ensure_pyusb():
    """Use the vendored pyusb when the system has none (keeps the tree self-contained)."""
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vendor = os.path.join(here, "vendor")
    if os.path.isdir(os.path.join(vendor, "usb")) and vendor not in sys.path:
        sys.path.insert(0, vendor)
    try:
        import usb.core  # noqa: F401
    except ImportError as exc:
        raise UsbError("pyusb is not available: %s" % exc)


def _load_backend():
    _ensure_pyusb()
    import usb.backend.libusb1 as libusb1

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local = os.path.join(here, "vendor", "windows", "x64", "libusb-1.0.dll")
    explicit = os.environ.get("IT9175_LIBUSB")
    if explicit:
        return libusb1.get_backend(find_library=lambda name: explicit)
    if os.name == "nt" and os.path.exists(local):
        return libusb1.get_backend(find_library=lambda name: local)
    return libusb1.get_backend()


def find_devices():
    """Yield pyusb device objects for the supported VID, one per matching PID."""
    _ensure_pyusb()
    import usb.core

    backend = _load_backend()
    if backend is None:
        raise UsbError("libusb backend not available (install libusb-1.0, or keep vendor/windows/x64/libusb-1.0.dll)")
    return list(usb.core.find(find_all=True, idVendor=VID, backend=backend))


class UsbBackend:
    """Bulk endpoint access to one dongle."""

    def __init__(self, dev, log=None):
        self.dev = dev
        self.log = log or (lambda msg: None)
        self.claimed = []

    @property
    def description(self):
        pid = self.dev.idProduct
        names = {PID_IT9175: "IT9175", PID_IT9308: "IT930x 9308", PID_IT9309: "IT930x 9309"}
        return "048d:%04x (%s) bus %s addr %s" % (pid, names.get(pid, "unknown"), self.dev.bus, self.dev.address)

    def _claim(self, intf):
        # pyusb keeps interface claiming on its private resource manager.
        ctx = getattr(self.dev, "_ctx", None)
        if ctx is not None and hasattr(ctx, "managed_claim_interface"):
            ctx.managed_claim_interface(self.dev, intf)
        else:
            self.dev.claim_interface(intf.bInterfaceNumber)

    def _release(self, intf):
        ctx = getattr(self.dev, "_ctx", None)
        if ctx is not None and hasattr(ctx, "managed_release_interface"):
            ctx.managed_release_interface(self.dev, intf)
        else:
            self.dev.release_interface(intf.bInterfaceNumber)

    def open(self):
        dev = self.dev
        try:
            dev.set_configuration()
        except Exception:
            pass
        wanted = {EP_CMD_OUT, EP_CMD_IN, EP_TS_IN}
        found = set()
        for cfg in dev:
            for intf in cfg:
                eps = {ep.bEndpointAddress for ep in intf}
                if not (eps & wanted):
                    continue
                try:
                    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                        dev.detach_kernel_driver(intf.bInterfaceNumber)
                except Exception:
                    pass
                try:
                    self._claim(intf)
                    self.claimed.append(intf)
                except Exception as exc:
                    raise UsbError("cannot claim interface %d: %s" % (intf.bInterfaceNumber, exc))
                found |= eps & wanted
        missing = wanted - found
        if missing:
            raise UsbError("missing endpoints: %s" % ", ".join("0x%02x" % e for e in sorted(missing)))
        return self

    def close(self):
        for intf in self.claimed:
            try:
                self._release(intf)
            except Exception:
                pass
        self.claimed = []

    def write(self, data, timeout_ms):
        return self.dev.write(EP_CMD_OUT, data, timeout_ms)

    def read(self, size, timeout_ms):
        return bytes(self.dev.read(EP_CMD_IN, size, timeout_ms))

    def read_ts(self, size, timeout_ms):
        return bytes(self.dev.read(EP_TS_IN, size, timeout_ms))


# ---------------------------------------------------------------------------
# Command link: sequence numbers, framing, timeouts
# ---------------------------------------------------------------------------

class Link:
    def __init__(self, backend, log=None, timeout_ms=1000):
        self.backend = backend
        self.log = log or (lambda msg: None)
        self.timeout_ms = timeout_ms
        self.seq = 0
        self.quiet = False

    def _next_seq(self):
        value = self.seq
        self.seq = (self.seq + 1) & 0xFF
        return value

    def _transact(self, frame, expect, what):
        try:
            written = self.backend.write(frame, self.timeout_ms)
        except Exception as exc:
            if not self.quiet:
                self.log("%s: write failed: %s" % (what, exc))
            return None
        if written != len(frame):
            if not self.quiet:
                self.log("%s: short write %d/%d" % (what, written, len(frame)))
            return None
        try:
            resp = self.backend.read(256, self.timeout_ms)
        except Exception as exc:
            if not self.quiet:
                self.log("%s: no response (%s)" % (what, exc))
            return None
        data = afa.parse_response(resp, expect)
        if data is None and not self.quiet:
            self.log("%s: bad response len=%d status=%s [%s]" % (
                what, len(resp), afa.status(resp), resp[:16].hex(" ")))
        return data

    # Tuner.Io interface ----------------------------------------------------
    def read(self, proc, addr, count):
        return self._transact(afa.build_read(self._next_seq(), 0, proc, addr, count),
                              count, "read 0x%x" % addr)

    def write(self, proc, addr, data):
        return self._transact(afa.build_write(self._next_seq(), 0, proc, addr, data),
                              0, "write 0x%x" % addr) is not None

    def command(self, cmd, proc, payload=None, reply_len=0):
        return self._transact(afa.build_command(cmd, self._next_seq(), 0, proc, payload),
                              reply_len, "cmd 0x%02x proc %d" % (cmd, proc))

    def fw_version(self, proc):
        return self.command(34, proc, b"\x01", 4)

    def sleep(self, ms):
        time.sleep(ms / 1000.0)


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

class It9175Device:
    def __init__(self, link, log=None, tuner_type=None, firmware_path=None):
        self.link = link
        self.log = log or (lambda msg: None)
        self.tuner_type = tuner_type
        self.firmware_path = firmware_path
        self.notes = []
        self.tuner = None
        self.locked = False
        self.firmware_simulated = False
        self.chip_version = -1
        self.chip_id = -1
        self._ts_pending = bytearray()

    def note(self, message):
        self.notes.append(message)
        self.log(message)

    # Tuner calls these ------------------------------------------------
    def read(self, proc, addr, count):
        return self.link.read(proc, addr, count)

    def write(self, proc, addr, data):
        return self.link.write(proc, addr, data)

    def fw_version(self, proc):
        return self.link.fw_version(proc) is not None

    def sleep(self, ms):
        self.link.sleep(ms)

    # -- bring-up -----------------------------------------------------------
    def init(self):
        ver = self.read(0, 0x1222, 1)
        ident = self.read(0, 0x1223, 2)
        if ver is None or ident is None:
            self.note("no answer from the LINK processor")
            return False
        self.chip_version = ver[0]
        self.chip_id = ident[0] | (ident[1] << 8)
        self.note("chip version=%d id=0x%04x" % (self.chip_version, self.chip_id))

        fw = self.link.fw_version(0)
        self.note("fw LINK before=%s" % (fw.hex(" ") if fw else "none"))
        if fw is None:
            return False
        if not any(fw):
            if not self.load_firmware():
                return False
            fw = self.link.fw_version(0)
            self.note("fw LINK after=%s" % (fw.hex(" ") if fw else "none"))
            if fw is None or not any(fw):
                self.note("firmware did not start (version still 0)")
                return False

        if not self.write(0, 0xF103, b"\x1a"):
            return False

        self.link.quiet = True
        self.link.timeout_ms = 400
        alive = self.write(8, 0xEC4C, b"\xa8")
        self.sleep(10)
        if not alive:
            alive = self.ofdm_alive()
        if not alive:
            self.note("OFDM silent after 0xec4c; running diagnostics")
            alive = self.diagnose_ofdm()
        self.link.quiet = False
        self.link.timeout_ms = 1000
        if not alive:
            self.note("OFDM processor does not answer; skipping script load")
            return False

        fw = self.link.fw_version(8)
        self.note("fw OFDM=%s" % (fw.hex(" ") if fw else "none"))
        self.note(self.diag_regs("before tuner init"))
        self.tuner = Tuner(self, self.note, self.tuner_type)
        ok = self.tuner.init()
        self.note(self.tuner.describe())
        self.note(self.diag_regs("after tuner init"))
        return ok

    def load_firmware(self):
        from . import firmware

        if not (self.write(0, 0x4BFB, b"\x00")
                and self.write(0, 0xCFFF, b"\x00")
                and self.write(0, 0xF103, b"\x07")):
            return False
        try:
            image = firmware.image(self.firmware_path)
        except FileNotFoundError:
            # A simulated dongle only counts the bytes; it never executes the
            # vendor image.  Allow the simulator and its tests to run on a tree
            # where the image is absent (the public snapshot withholds it).
            if not getattr(self.link.backend, "is_simulated", False):
                raise
            image = bytes(firmware.SIZE)
            self.firmware_simulated = True
            self.note("simulated firmware: %d zero bytes uploaded (no vendor image read)"
                      % firmware.SIZE)
        offset = 0
        for index, size in enumerate(firmware.CHUNKS):
            chunk = image[offset:offset + size]
            offset += size
            if self.link.command(41, 0, chunk, 0) is None:
                self.note("firmware chunk %d failed" % index)
                return False
        if self.link.command(35, 0, None, 0) is None:
            self.note("firmware start command failed")
            return False
        self.sleep(10)
        self.note("firmware downloaded (%d bytes)" % offset)
        return True

    def ofdm_alive(self):
        return self.read(8, 0x46, 1) is not None

    def rd(self, proc, addr):
        value = self.read(proc, addr, 1)
        return "--" if value is None else "%02x" % value[0]

    def set_bit0(self, addr):
        value = self.read(0, addr, 1)
        if value is None:
            return False
        return self.write(0, addr, bytes([value[0] | 1]))

    def diag_regs(self, when):
        regs = [(0, 0x461B), (0, 0x49AC), (0, 0xD800), (0, 0xD805), (0, 0xDD11),
                (8, 0x4D), (8, 0x1C6), (8, 0x1DC), (8, 0xEC86), (8, 0xED03),
                (8, 0xED23), (8, 0xED24), (8, 0xED81), (8, 0xEC4C)]
        quiet = self.link.quiet
        self.link.quiet = True
        text = "regs %s:" % when
        for proc, addr in regs:
            text += " %s%04x=%s" % ("L" if proc == 0 else "O", addr, self.rd(proc, addr))
        self.link.quiet = quiet
        return text

    def diagnose_ofdm(self):
        quiet = self.link.quiet
        self.link.quiet = True
        link = [0xD800, 0xF103, 0xD8C8, 0xD8C9, 0xD8BC, 0xD8BD, 0xD8BB, 0xE00C, 0xF641, 0x4BFB, 0xCFFF]
        ofdm = [0xF84F, 0xFBB9, 0xEC40, 0xEC4C, 0x43, 0x46]
        self.note("LINK regs: " + " ".join("%04x=%s" % (a, self.rd(0, a)) for a in link))
        self.note("OFDM regs: " + " ".join("%04x=%s" % (a, self.rd(8, a)) for a in ofdm))
        self.link.quiet = quiet
        if self.ofdm_alive():
            return True
        for _ in range(5):
            self.link.fw_version(0)
            self.sleep(1)
        self.write(8, 0xEC40, b"\x01")
        self.sleep(10)
        self.note("A (ApCtrl dummy + 0xec40=1): %s" % ("OFDM ALIVE" if self.ofdm_alive() else "silent"))
        if self.ofdm_alive():
            return True
        self.write(0, 0xE00C, b"\x00")
        self.write(8, 0xF84F, b"\x00")
        self.write(8, 0xF84F, b"\x01")
        self.sleep(50)
        self.note("B (power-saving exit): %s" % ("OFDM ALIVE" if self.ofdm_alive() else "silent"))
        if self.ofdm_alive():
            return True
        for addr in (0xD8C8, 0xD8C9, 0xD8BC, 0xD8BD):
            self.set_bit0(addr)
        self.sleep(50)
        self.note("C (GPIO bits): %s" % ("OFDM ALIVE" if self.ofdm_alive() else "silent"))
        if self.ofdm_alive():
            return True
        fw = self.link.fw_version(8)
        self.note("fw OFDM query: %s" % (fw.hex(" ") if fw else "none"))
        return fw is not None

    # -- tuning -------------------------------------------------------------
    def tune(self, freq_khz, quick=False):
        if self.tuner is None:
            self.note("tune: tuner not initialised")
            return False
        started = time.time()
        if not self.tuner.tune(freq_khz):
            self.note("tune %d kHz: FAILED" % freq_khz)
            return False
        self.sleep(50)
        self.locked = self.tuner.wait_lock(quick)
        status = self.tuner.status()
        self.locked = self.locked and status["locked"]
        status["locked"] = self.locked
        self.note("tune %d kHz: programmed in %d ms, lock=%s after %d ms" % (
            freq_khz, int((time.time() - started) * 1000), self.locked,
            int((time.time() - started) * 1000)))
        self.note("signal raw: strength=%d quality=%d snr=%d dbm=%d berErr=%d berWin=%d" % (
            status["raw_strength"], status["raw_quality"], status["raw_snr"],
            status["dbm"], status["ber_errors"], status["ber_window"]))
        return self.locked

    def status(self):
        return self.tuner.status() if self.tuner else None

    def read_ts(self, size=TS_READ_SIZE, timeout_ms=500, align=True):
        data = self.link.backend.read_ts(size, timeout_ms)
        if not align:
            return data
        return self._align_ts(data)

    def _align_ts(self, data):
        """Return whole 188-byte packets, locking onto the sync phase once.

        The demodulator can start a bulk read in the middle of a packet, so the
        first chunk is used to find the offset where 0x47 repeats every 188 B.
        """
        self._ts_pending += data
        buffer = self._ts_pending
        if not buffer:
            return b""

        phase = 0
        while phase < 188:
            usable = len(buffer) - phase
            if usable >= 376:
                if buffer[phase] == 0x47 and buffer[phase + 188] == 0x47:
                    break
                phase += 1
            elif usable >= 188:
                if buffer[phase] == 0x47:
                    break
                phase += 1
            else:
                return b""          # need more bytes to decide
        else:
            self._ts_pending = buffer[-376:]
            return b""

        if phase:
            buffer = buffer[phase:]
            self._ts_pending = buffer

        count = len(buffer) // 188 * 188
        if not count:
            return b""
        out = bytes(buffer[:count])
        self._ts_pending = buffer[count:]

        # If the phase ever drifts, drop the buffer and lock again next read.
        for offset in range(0, len(out), 188):
            if out[offset] != 0x47:
                self._ts_pending = bytearray()
                return b""
        return out

    def probe_report(self):
        text = ["open: True", "init: %s" % ("ok" if self.tuner else "failed")]
        if self.tuner:
            try:
                data = self.read_ts(TS_READ_SIZE, 1000)
                text.append("TS read on 0x84: %d bytes, first byte 0x%02x" % (len(data), data[0] if data else 0))
            except Exception as exc:
                text.append("TS read failed: %s" % exc)
        text.extend(self.notes)
        return "\n".join(text)


# ---------------------------------------------------------------------------
# Fake backend for tests and `it9175 sim`
# ---------------------------------------------------------------------------

class SimBackend:
    """Register-level fake: enough behaviour to run init, tune and TS reads."""

    is_simulated = True

    def __init__(self):
        self.regs = {}
        self.oneshot = set()
        self.fw_loaded = False
        self.commands = []
        self.firmware_bytes = 0
        self.writes = 0
        self._seed()

    def _seed(self):
        self.regs[(0, 0x1222)] = 1
        self.regs[(0, 0x1223)] = 0x75
        self.regs[(0, 0x1224)] = 0x91
        self.regs[(0, 0xD800)] = 0x00
        self.regs[(0, 0xD8CF)] = 0x02
        self.regs[(8, 0xEC86)] = 0
        self.regs[(8, 0xED03)] = 3
        self.regs[(8, 0xED23)] = 0x22
        self.regs[(8, 0xED24)] = 0x12
        self.regs[(8, 0xEC4C)] = 0xA8
        self.regs[(8, 0x1C6)] = 1
        self.regs[(8, 0x1DC)] = 0
        self.regs[(8, 0x47)] = 1
        self.regs[(8, 0xF5A9)] = 1
        self.regs[(8, 0xF9F1)] = 1
        self.regs[(8, 0x13E)] = 72
        self.regs[(8, 0x49)] = 80
        self.regs[(8, 0x13F)] = 150
        self.regs[(8, 0x1C9)] = 28
        for i in range(7):
            self.regs[(8, 0x32 + i)] = 0
        self.regs[(8, 0x34)] = 0x12          # BER error count, 24-bit
        self.regs[(8, 0x37)] = 0x10          # BER window, 16-bit
        self.regs[(8, 0x38)] = 0x27

    def open(self):
        return self

    def close(self):
        pass

    def _get(self, proc, addr):
        if (proc, addr) in self.oneshot:
            # Command/status registers such as 0x4c clear themselves after the
            # firmware has consumed the write.
            self.oneshot.discard((proc, addr))
            self.regs[(proc, addr)] = 0
            return 1
        if proc == 8 and addr == 0x47:
            # The demod reports lock a few milliseconds after TUNE_PRE clears it.
            return 1
        return self.regs.get((proc, addr), 0)

    def write(self, frame, timeout_ms):
        cmd = frame[2]
        seq = frame[3]
        if cmd == afa.CMD_WRITE_REGISTERS:
            count = frame[4]
            addr = (frame[6] << 24) | (frame[7] << 16) | (frame[8] << 8) | frame[9]
            proc = (frame[1] >> 4) & 0x0F
            for i in range(count):
                self.regs[(proc, addr + i)] = frame[10 + i]
            if proc == 8 and addr == 0x4C:
                self.oneshot.add((8, 0x4C))
            self.writes += 1
            self.last = ("write", proc, addr, bytes(frame[10:10 + count]))
        elif cmd == afa.CMD_READ_REGISTERS:
            self.last = ("read", (frame[1] >> 4) & 0x0F,
                         (frame[6] << 24) | (frame[7] << 16) | (frame[8] << 8) | frame[9], frame[4])
        else:
            payload = bytes(frame[4:-2])
            self.commands.append(cmd)
            self.last = ("cmd", cmd, payload)
            if cmd == 34:
                self.last = ("cmd34",)
            elif cmd == 41:
                self.firmware_bytes += len(payload)
            elif cmd == 35:
                self.fw_loaded = True
        return len(frame)

    def read(self, size, timeout_ms):
        kind = self.last[0]
        body = bytearray()
        if kind == "cmd34":
            value = b"\x05\x05\x00\x00" if self.fw_loaded else b"\x00\x00\x00\x00"
            body += value[:size]
        elif kind == "read":
            _, proc, addr, count = self.last
            for i in range(count):
                body.append(self._get(proc, addr + i))
        # cmd/write responses carry no payload
        frame = bytearray(5 + len(body))
        frame[0] = len(frame) - 1
        frame[1] = 0
        frame[2] = 0
        frame[3:3 + len(body)] = body
        cs = afa.checksum(frame, len(frame) - 2)
        frame[-2] = (cs >> 8) & 0xFF
        frame[-1] = cs & 0xFF
        return bytes(frame)

    def read_ts(self, size, timeout_ms):
        packets = size // 188
        out = bytearray()
        for i in range(packets):
            pkt = bytearray([0xFF] * 188)
            pkt[0] = 0x47
            pkt[1] = 0x1F
            pkt[2] = 0xFF
            pkt[3] = 0x10 | ((i >> 8) & 0x0F)
            pkt[4] = i & 0xFF
            out += pkt
        return bytes(out[:size])
