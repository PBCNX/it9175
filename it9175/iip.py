"""IIP: the ISDB-T Information Packet (PID 0x1FF0), the frame-ahead transmission-control packet.

One TSP per multiplex frame, carried in the invalid hierarchy rather than in a layer. Its 184-byte
payload describes the multiplex frame **after** the one carrying it:

    IIP_packet_pointer                              16  uimsbf
    modulation_control_configuration_information   160  bslbf
        mode_GI_information: init timing 4, current mode 2, current guard 2, next mode 2, next guard 2
        TMCC_information:    system id 2, countdown 4, B26 1, partial 1,
                             current layers A/B/C (13 bits each: modulation 3, code rate 3,
                             interleave 3, segments 4), next partial 1, next layers A/B/C,
                             phase 3, reserved 12, reserved 10
        CRC_32                                      32
    IIP_branch_number 8 | last_IIP_branch_number 8 | network_synchronization_information_length 8 | ...

Two things make it worth decoding on this chip:

* it carries **mode and guard interval**, which the 9175's TMCC words also expose (0xF900) - so it is an
  independent confirmation of those fields from the stream itself;
* it carries the **B26 (EWBS) copy for the next frame**, so a receiver whose demod exposes no activation
  bit can still see the alarm - including the flag-only case where the PMT carries no 0xFC descriptor.

Ported from the IT9308 research line's decoder (`it9308/iip.py`, MIT), which implemented ARIB STD-B31
v2.2-E1 Tables 5-8 and 5-10. Validated here against the real EWBS Test Streams capture: two
configurations, ewbs 0/1, 8K, 1/16, partial 1, A QPSK 2/3 I4 1seg, B 64QAM 3/4 I1 12seg - the same
values the demod's TMCC words report, with layer B's interleave confirmed independently.
"""

MODES = {1: "2K", 2: "4K", 3: "8K"}
GUARDS = {0: "1/32", 1: "1/16", 2: "1/8", 3: "1/4"}
MODULATIONS = {0: "DQPSK", 1: "QPSK", 2: "16QAM", 3: "64QAM"}
CODE_RATES = {0: "1/2", 1: "2/3", 2: "3/4", 3: "5/6", 4: "7/8"}
INTERLEAVES = {0: "I0", 1: "I1", 2: "I2", 3: "I4"}
UNKNOWN = "?"
UNUSED = 7

#: The TSP PID the IIP is carried on.
PID = 0x1FF0


class Bits:
    def __init__(self, data):
        self.bits = [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]
        self.position = 0

    def take(self, count):
        value = 0
        for _ in range(count):
            value = (value << 1) | self.bits[self.position]
            self.position += 1
        return value


class Layer:
    def __init__(self):
        self.present = False
        self.modulation = UNKNOWN
        self.code_rate = UNKNOWN
        self.interleave = UNKNOWN
        self.segments = 0

    def __str__(self):
        if not self.present:
            return "-"
        return "%s %s %s %dseg" % (self.modulation, self.code_rate, self.interleave, self.segments)


class Iip:
    def __init__(self):
        self.pointer = 0
        self.mode = UNKNOWN
        self.guard = UNKNOWN
        self.next_mode = UNKNOWN
        self.next_guard = UNKNOWN
        self.ewbs = False
        self.partial = False
        self.layer_a = Layer()
        self.layer_b = Layer()
        self.layer_c = Layer()
        self.branch = 0
        self.last_branch = 0
        self.net_sync_length = 0
        self.crc_ok = False

    def __str__(self):
        return ("iip mode %s guard %s partial %d ewbs %d L0:%s L1:%s L2:%s next %s/%s crc %s"
                % (self.mode, self.guard, int(self.partial), int(self.ewbs),
                   self.layer_a, self.layer_b, self.layer_c, self.next_mode, self.next_guard,
                   "ok" if self.crc_ok else "FAIL"))

    @property
    def segments(self):
        return sum(layer.segments for layer in (self.layer_a, self.layer_b, self.layer_c))


def crc32_mpeg2(data):
    """ISO/IEC 13818-1 CRC-32 (STD-B31 Table 5-10 ``CRC_32``): poly 0x04C11DB7, init 0xFFFFFFFF.

    No reflection and no final XOR. Covers the MCCI from ``TMCC_synchronization_word`` to
    ``reserved_future_use`` - the first 16 of its 20 bytes; the value is stored big-endian in the
    last four. A receiver that shows an alert should check this: a corrupt packet must not become one.
    """
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _layer(reader):
    modulation = reader.take(3)
    code = reader.take(3)
    interleave = reader.take(3)
    segments = reader.take(4)
    layer = Layer()
    layer.present = modulation != UNUSED and segments != 15
    if layer.present:
        layer.modulation = MODULATIONS.get(modulation, UNKNOWN)
        layer.code_rate = CODE_RATES.get(code, UNKNOWN)
        layer.interleave = INTERLEAVES.get(interleave, UNKNOWN)
        layer.segments = segments
    return layer


def decode(payload):
    """Decode one IIP payload (the 184 bytes after the 4-byte TSP header)."""
    if len(payload) < 25:
        raise ValueError("IIP payload too short: %d bytes" % len(payload))
    iip = Iip()
    iip.pointer = (payload[0] << 8) | payload[1]
    reader = Bits(payload[2:22])          # the 160-bit MCCI block
    reader.take(1)                        # TMCC synchronization word
    reader.take(1)                        # AC data effective position
    reader.take(2)                        # reserved
    reader.take(4)                        # initialization timing indicator
    iip.mode = MODES.get(reader.take(2), UNKNOWN)
    iip.guard = GUARDS.get(reader.take(2), UNKNOWN)
    iip.next_mode = MODES.get(reader.take(2), UNKNOWN)
    iip.next_guard = GUARDS.get(reader.take(2), UNKNOWN)
    reader.take(2)                        # system identifier
    reader.take(4)                        # count down index
    iip.ewbs = bool(reader.take(1))       # B26 copy for the next frame
    iip.partial = bool(reader.take(1))
    iip.layer_a = _layer(reader)
    iip.layer_b = _layer(reader)
    iip.layer_c = _layer(reader)
    reader.take(1)                        # next partial reception flag
    _layer(reader), _layer(reader), _layer(reader)   # next-frame layers
    reader.take(3 + 12 + 10)              # phase, reserved, reserved
    mcci = payload[2:22]
    iip.crc_ok = crc32_mpeg2(mcci[:16]) == int.from_bytes(mcci[16:20], "big")
    iip.branch = payload[22]
    iip.last_branch = payload[23]
    iip.net_sync_length = payload[24]
    return iip
