"""IT9175 tuner control: register scripts, tuning maths and status.

Port of OpenDTV's ph.opendtv.source.It9175Tuner. The script tables and the
arithmetic are kept verbatim so the behaviour matches the verified Android
driver; only the IO layer is abstract (see it9175.device).
"""
from . import tables

LINK = 0
OFDM = 8
BW_KHZ = 6000

NV = [48, 32, 24, 16, 12, 8, 6, 4, 2]


class TunerError(RuntimeError):
    pass


class Tuner:
    def __init__(self, io, log=None, tuner_type_override=None):
        self.io = io
        self.log = log or (lambda msg: None)
        self.tuner_type_override = tuner_type_override
        self.clock = -1
        self.tuner_type = 0
        self.ed03 = 0
        self.ed23 = 0
        self.mul_p = 0
        self.mul_q = 1
        self.thr = [53000, 74000, 111000, 148000, 222000, 296000, 445000, 573000, 950000]
        self.init_done = False
        self.flag = False
        self.last_freq_khz = 0

    # -- io helpers ---------------------------------------------------------
    def rd(self, proc, addr):
        b = self.io.read(proc, addr, 1)
        if b is None:
            return -1
        return b[0]

    def wr(self, proc, addr, value):
        return self.io.write(proc, addr, bytes([value & 0xFF]))

    @staticmethod
    def unhex(text):
        return bytes.fromhex(text)

    # -- script interpreter -------------------------------------------------
    def exec_op(self, op):
        kind = op[0]
        proc = ord(op[1]) - ord("0")
        parts = op[3:].split(":") if len(op) > 3 else [""]
        if kind == "I":
            if self.flag and not self.io.write(proc, int(parts[0], 16), self.unhex(parts[1])):
                return False
            return True
        if kind == "M":
            addr = int(parts[0], 16)
            value = self.rd(proc, addr)
            if value < 0:
                return False
            return self.wr(proc, addr, (int(parts[1], 16) & value) | int(parts[2], 16))
        if kind == "P":
            addr = int(parts[0], 16)
            for _ in range(150):
                value = self.rd(proc, addr)
                if value < 0:
                    return False
                if value == 0:
                    return True
                self.io.sleep(2)
            self.log("poll 0x%x timed out" % addr)
            return True
        if kind == "Q":
            value = self.rd(proc, int(parts[0], 16))
            if value < 0:
                return False
            self.flag = value != 0
            return True
        if kind == "V":
            return self.io.fw_version(proc)
        if kind == "W":
            return self.io.write(proc, int(parts[0], 16), self.unhex(parts[1]))
        raise TunerError("bad op %r" % op)

    def run(self, ops):
        for op in ops:
            if not self.exec_op(op):
                self.log("op failed: %s" % op)
                return False
        return True

    def clock_index(self):
        return 0 if self.clock == 0 else 1

    # -- init ---------------------------------------------------------------
    def init(self):
        self.init_done = False
        d800 = self.rd(LINK, 0xD800)
        if d800 < 0:
            return False
        self.clock = d800 & 15
        self.log("LINK 0xd800=0x%02x -> clock index %d" % (d800, self.clock))
        if self.clock > 1:
            self.log("clock index > 1: vendor takes an unported path, falling back to index-1 tables")
        if not self.run(tables.INIT_A0 if self.clock_index() == 0 else tables.INIT_A1):
            return False
        if not self.samba_init():
            return False
        if not self.run(tables.INIT_B0 if self.clock_index() == 0 else tables.INIT_B1):
            return False
        if not self.run(["M8:f993:fe:00", "M8:f992:fe:01", "W8:1e7:00"]):
            return False
        self.init_done = True
        return True

    def samba_init(self):
        tuner_type = self.rd(OFDM, 0xEC86)
        if self.tuner_type_override is not None:
            tuner_type = self.tuner_type_override
        ed03 = self.rd(OFDM, 0xED03)
        pair = self.io.read(OFDM, 0xED23, 2)
        if tuner_type < 0 or ed03 < 0 or pair is None:
            return False
        self.tuner_type = tuner_type
        self.ed03 = ed03
        value = pair[0] | (pair[1] << 8)
        if tuner_type == 0:
            self.mul_p, self.mul_q, ed81 = 2000, 3, 16
        elif tuner_type == 1:
            self.mul_p, self.mul_q, ed81 = 20480, 18, 6
        else:
            self.mul_p, self.mul_q, ed81 = 640, 1, 6

        tries = 1
        while value == 0 and tries <= 49:
            self.io.sleep(2)
            pair = self.io.read(OFDM, 0xED23, 2)
            if pair is None:
                return False
            value = pair[0] | (pair[1] << 8)
            tries += 1
        self.ed23 = value
        self.log("tuner fw: ec86=%d ed03=%d ed23=%d" % (tuner_type, ed03, value))
        if value == 0:
            self.log("tuner firmware did not report its clock (ed23 stayed 0)")
            return False

        nv = get_nv(ed03)
        x5 = value * self.mul_p
        x8 = x5 // self.mul_q
        x7 = (x8 * 0xAAAAAAAAAAAAAAAB) >> 64
        self.thr[5] = (x8 >> 3) & 0xFFFFFFFF
        self.thr[3] = (x8 >> 4) & 0xFFFFFFFF
        self.thr[7] = (x5 // (self.mul_q * nv)) & 0xFFFFFFFF
        self.thr[1] = (x8 >> 5) & 0xFFFFFFFF
        self.thr[6] = (x7 >> 2) & 0xFFFFFFFF
        self.thr[4] = (x7 >> 3) & 0xFFFFFFFF
        self.thr[2] = (x7 >> 4) & 0xFFFFFFFF

        self.rd(LINK, 0x1222)
        if self.io.read(LINK, 0x1223, 2) is None:
            return False
        self.io.sleep(50)
        if not self.wr(OFDM, 0xED81, ed81):
            return False
        r1dc = self.rd(OFDM, 0x1DC)
        if r1dc < 0:
            return False
        if r1dc == 1:
            return self.run(["M0:d8d0:fe:01", "M0:d8d1:fe:01"])
        return True

    # -- tuning maths -------------------------------------------------------
    def get_nc(self, freq):
        if self.thr[1] >= freq:
            return 0
        if freq <= self.thr[2]:
            return 1
        if freq <= self.thr[3]:
            return 2
        if freq <= self.thr[4]:
            return 3
        if freq <= self.thr[5]:
            return 4
        if freq <= self.thr[6]:
            return 5
        if freq <= self.thr[7]:
            return 6
        return 7 if freq <= self.thr[8] else 8

    def freq_code(self, freq):
        nc = self.get_nc(freq)
        nv = get_nv(nc)
        prod = self.mul_q * freq * nv
        den = self.mul_p
        q, rem = divmod(prod, den)
        if rem >= (den >> 1):
            q += 1
        return nc, nv, q & 0xFFFFFFFF

    def lo_freq(self, freq):
        nc, _nv, fcw = self.freq_code(freq)
        return (((nc & 7) << 13) + fcw) & 0xFFFFFFFF

    def cal_freq_iqik(self, freq, p):
        nc, nv, fcw = self.freq_code(freq)
        if self.tuner_type == 0:
            if p <= 31:
                x = ((9 * nv * p) >> 5) + fcw
            else:
                x = fcw - ((9 * nv * ((64 - p) & 255)) >> 5)
        elif p <= 31 and self.tuner_type == 1:
            x = ((p * nv) >> 1) + fcw
        else:
            x = fcw - ((((64 - p) & 255) * nv) >> 1)
        return (((7 & nc) << 13) + x) & 0xFFFFFFFF

    # -- tune ---------------------------------------------------------------
    def tune(self, freq_khz):
        if not self.init_done:
            self.log("tune before init")
            return False
        freq = freq_khz & 0xFFFFFFFF
        if not self.run(tables.TUNE_PRE0 if self.clock_index() == 0 else tables.TUNE_PRE1):
            return False
        if freq <= 29999:
            v4b = 255
        elif freq <= 300000:
            v4b = 0
        elif freq <= 1000000:
            v4b = 1
        else:
            v4b = 255 if (freq - 1670000) > 10000 else 2
        if not self.wr(OFDM, 0x4B, v4b):
            return False

        r1c6 = self.rd(OFDM, 0x1C6)
        r1dc = self.rd(OFDM, 0x1DC)
        if r1c6 < 0 or r1dc < 0:
            return False
        if r1c6 != 0:
            row = self.band_row(tables.BANDS1 if r1dc == 1 else tables.BANDS0, freq)
            writes = [
                (0xFB25, row[1]), (0xFBB5, row[2]), (0xFBB6, row[3]), (0xFBB7, row[4]),
                (0xFBB9, row[5]), (0xFBB9, row[6]), (0xFBBA, row[7]),
            ]
            for addr, value in writes:
                if not self.wr(OFDM, addr, value):
                    return False
        if not self.samba_set_freq(freq, BW_KHZ):
            return False
        if not self.wr(OFDM, 0x00, 0):
            return False
        self.last_freq_khz = freq_khz
        return True

    @staticmethod
    def band_row(table, freq):
        row = table[0]
        for candidate in table:
            if candidate[0] > freq:
                break
            row = candidate
        return row

    def samba_set_freq(self, freq, bw_khz):
        ec4c = self.rd(OFDM, 0xEC4C)
        ed81 = self.rd(OFDM, 0xED81)
        if ec4c < 0 or ed81 < 0:
            return False
        lna = lna_cap_sel(freq)
        lpf = lpf_bw(bw_khz)
        b5a = (ec4c & 231) | (8 if freq > 311999 else 0)
        iq = self.cal_freq_iqik(freq, ed81)
        lo = self.lo_freq(freq)
        writes = [
            (0x160, lna), (0xEC56, lpf), (0xEC4C, b5a),
            (0xEC4D, iq & 0xFF), (0xEC4E, (iq >> 8) & 0xFF),
            (0x15E, lo & 0xFF), (0x15F, (lo >> 8) & 0xFF),
        ]
        for addr, value in writes:
            if not self.wr(OFDM, addr, value):
                return False
        r1dc = self.rd(OFDM, 0x1DC)
        if r1dc < 0:
            return False
        if r1dc == 1:
            r = self.rd(LINK, 0xD8CF)
            if r < 0:
                return False
            if not self.wr(LINK, 0xD8CF, (r & 254) | (1 if freq > 176142 else 0)):
                return False
        half = freq >> 1
        hl = self.lo_freq(half)
        return (self.wr(OFDM, 0x1E3, lna_cap_sel(half))
                and self.wr(OFDM, 0x1E1, hl & 0xFF)
                and self.wr(OFDM, 0x1E2, (hl >> 8) & 0xFF))

    # -- lock and status ----------------------------------------------------
    def mpeg2_locked(self):
        a = self.rd(OFDM, 0xF9F1)
        b = self.rd(OFDM, 0xF9F2)
        c = self.rd(OFDM, 0xF9F3)
        return a >= 0 and b >= 0 and c >= 0 and ((a | b | c) & 1) != 0

    def wait_lock(self, quick=False):
        attempts = 1 if quick else 2
        for attempt in range(attempts):
            poll = 60 if quick else 40
            state = 0
            for _ in range(poll):
                state = self.rd(OFDM, 0x47)
                if state in (1, 2) or state < 0:
                    break
                self.io.sleep(25)
            if state == 1:
                tps = False
                for _ in range(50):
                    value = self.rd(OFDM, 0xF5A9)
                    tps = value >= 0 and (value & 1) != 0
                    if tps:
                        break
                    self.io.sleep(25)
                if tps:
                    for _ in range(40):
                        if self.mpeg2_locked():
                            return True
                        self.io.sleep(25)
            if state == 2 and attempt == 1:
                break
            self.wr(OFDM, 0x47, 0)
            self.wr(LINK, 0x00, 0)
        return False

    def status(self):
        tps = self.rd(OFDM, 0xF5A9)
        locked = tps >= 0 and (tps & 1) != 0 and self.mpeg2_locked()
        result = {
            "locked": locked,
            "raw_strength": -1, "strength_percent": -1,
            "raw_quality": -1, "quality_percent": -1,
            "dbm": -1000, "raw_snr": -1, "snr_db": None,
            "ber_errors": -1, "ber_window": -1, "ber": None,
        }
        strength = self.rd(OFDM, 0x13E)
        if strength >= 0:
            result["raw_strength"] = strength
            result["strength_percent"] = min(strength, 100)
        quality = self.rd(OFDM, 0x49)
        if quality >= 0:
            result["raw_quality"] = quality
            result["quality_percent"] = min(quality, 100)
        dbm = self.rd(OFDM, 0x13F)
        if dbm >= 0:
            result["dbm"] = dbm - 100
        snr = self.rd(OFDM, 0x1C9)
        if snr >= 0:
            result["raw_snr"] = snr
            result["snr_db"] = snr
        b = self.io.read(OFDM, 0x32, 7)
        if b is not None:
            window = b[5] | (b[6] << 8)
            err = b[2] | (b[3] << 8) | (b[4] << 16)
            result["ber_errors"] = err
            result["ber_window"] = window
            if window:
                result["ber"] = err / (window * 204.0 * 8.0)
        return result

    def describe(self):
        return ("clock=%d tunerType=%d ed03=%d ed23=%d thr=[%d %d %d %d %d %d %d %d]"
                % (self.clock, self.tuner_type, self.ed03, self.ed23,
                   self.thr[1], self.thr[2], self.thr[3], self.thr[4],
                   self.thr[5], self.thr[6], self.thr[7], self.thr[8]))


def get_nv(index):
    if index < 0 or index > 8:
        return 2
    return NV[index]


def lna_cap_sel(freq):
    if freq <= 440000:
        return 0
    if freq <= 484000:
        return 1
    if freq <= 533000:
        return 2
    if freq <= 587000:
        return 3
    if freq <= 645000:
        return 4
    if freq <= 710000:
        return 5
    return 6 if ((freq - 710001) & 0xFFFFFFFF) <= 71999 else 7


def lpf_bw(bw_khz):
    return {5000: 0, 5500: 1, 6000: 2, 6500: 3, 7000: 4,
            7500: 5, 8000: 6, 8500: 7}.get(bw_khz, 6)
