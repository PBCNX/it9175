"""TMCC: the ISDB-T transmission parameters, as the IT9175's demod reports them.

The demod decodes the TMCC signal itself and publishes the result in eight
16-bit registers on the OFDM processor.  The field map below was found by
transmitting a controlled mux (DekTec DTA-115) with one parameter changed at a
time and diffing the register space; each line carries the evidence.

    register   meaning
    ---------  --------------------------------------------------------------
    0xF900     mode (bits 15:8: 0=2K, 1=8K, 2=4K) + guard (bits 7:0)
    0xF902     partial reception (bit 8) + layer A modulation (bits 1:0)
    0xF904     layer A code rate (bits 15:8) + layer A interleave (bits 1:0)
    0xF906     layer A segments (bits 15:8)
    0xF908     layer B code rate (bits 15:8) + layer B interleave (bits 1:0)
    0xF90A     layer B segments (bits 15:8)
    0xF90C     layer C code rate (bits 15:8) + layer C interleave (bits 1:0)
    0xF90E     layer C segments (bits 15:8)

Evidence, one controlled change per run:

* mode: 2K -> 0x0002, 4K -> 0x0202, 8K -> 0x0102 (DTA-115 Mode 1/2/3, and the
  bridge's 8K mux reads the same as the 8K StreamXpress run);
* guard: 1/32 -> 0, 1/16 -> 1, 1/8 -> 2, 1/4 -> 3 (three settings; CH14 473143
  reads 2 = 1/8, matching the DIB0700 line's independent record of that mux);
* partial: 0 -> 1 with nothing else moving when the transmitter toggled it;
* modulation: DQPSK=0, QPSK=1, 16QAM=2, 64QAM=3;
* code rate: 1/2=0, 2/3=1, 3/4=2, 5/6=3 (7/8 is the expected 4);
* interleave: 0,1,2,4 on air map to 0,1,2,3;
* segments: one byte per layer, 0x0F means "layer not in use".

Validated end to end against the real  EWBS capture (EWBS Test Streams):
the demod reads 8K / 1/16 / partial 1 / layer A 1 seg QPSK 2/3 I4 / layer B 12 seg,
which is exactly that broadcast's layout (NIT partial_reception service 0x0A58,
three services: HD, SD, Mobile).

The code-rate table below is 0-based and correct - the "partial layer reads one step
low" caveat of 2026-11-19 is withdrawn (2026-11-20). DIB0700's reference labels were 0-based
while their kernel table was 1-based, so their labels sat one step high; corrected, 479 raw 7
-> 7/8, 485 raw 2 -> 2/3, 497 raw 3 -> 3/4, all matching this map. The IT9308 settled it from
STD-B31 Table 3-23 (modulation bits 7:5, code rate bits 4:2): two lock-verified channels read
479 = 7/8 and 497 = 3/4, the same values this driver reports. No offset was ever needed.
"""

MODES = {0: "2K", 1: "8K", 2: "4K"}
GUARDS = {0: "1/32", 1: "1/16", 2: "1/8", 3: "1/4"}
MODULATIONS = {0: "DQPSK", 1: "QPSK", 2: "16QAM", 3: "64QAM"}
CODE_RATES = {0: "1/2", 1: "2/3", 2: "3/4", 3: "5/6", 4: "7/8"}
INTERLEAVES = {0: 0, 1: 1, 2: 2, 3: 4}
NO_LAYER = 0x0F
NO_MODULATION = 0x07

#: Registers read from the OFDM processor (8) to build a Tmcc record.
REGISTERS = (0xF900, 0xF902, 0xF904, 0xF906, 0xF908, 0xF90A, 0xF90C, 0xF90E)


class Tmcc:
    """One TMCC read: mode, guard, partial reception and the three layers."""

    def __init__(self, mode, guard, partial, layers):
        self.mode = mode            # "2K" | "8K" | "4K" | None
        self.guard = guard          # "1/32" | "1/16" | "1/8" | "1/4" | None
        self.partial = partial      # bool
        self.layers = layers        # list of dicts: segments, modulation, code_rate, interleave

    @property
    def segments(self):
        return [layer["segments"] for layer in self.layers]

    @property
    def valid(self):
        """True when the fields describe a real ISDB-T channel."""
        return (self.mode is not None and self.guard is not None
                and 1 <= sum(self.segments) <= 13)

    def layer(self, index):
        return self.layers[index]

    def __str__(self):
        parts = ["mode %s guard %s partial %d"
                 % (self.mode or "?", self.guard or "?", 1 if self.partial else 0)]
        for index, layer in enumerate(self.layers):
            if layer["segments"] == 0:
                parts.append("L%d:-" % index)
                continue
            parts.append("L%d:%s %dseg code %s I%d"
                         % (index, layer["modulation"], layer["segments"],
                            layer["code_rate"], layer["interleave"]))
        return " ".join(parts)

    def as_dict(self):
        return {"mode": self.mode, "guard": self.guard,
                "partial": self.partial, "layers": list(self.layers),
                "valid": self.valid}


def _word(words, register):
    value = words.get(register)
    return 0 if value is None else value


def _segments(value):
    high = (value >> 8) & 0xFF
    return 0 if high == NO_LAYER else high


def _modulation(value, shift):
    code = (value >> shift) & 0x07
    return None if code == NO_MODULATION else MODULATIONS.get(code)


def decode(words):
    """Build a :class:`Tmcc` from a register -> value mapping.

    ``words`` is keyed by register number (see :data:`REGISTERS`) with 16-bit
    values, as read from the OFDM processor.
    """
    control = _word(words, 0xF900)
    mode = MODES.get((control >> 8) & 0x03)
    guard = GUARDS.get(control & 0x03)

    layer_a_control = _word(words, 0xF902)
    partial = bool((layer_a_control >> 8) & 0x01)

    a_segments = _word(words, 0xF906)
    b_segments = _word(words, 0xF90A)
    a = _word(words, 0xF904)
    b = _word(words, 0xF908)
    c = _word(words, 0xF90C)
    layers = [
        {"segments": _segments(a_segments),
         "modulation": _modulation(layer_a_control, 0),
         "code_rate": CODE_RATES.get((a >> 8) & 0x07),
         "interleave": INTERLEAVES.get(a & 0x03)},
        {"segments": _segments(b_segments),
         "modulation": _modulation(a_segments, 0),
         "code_rate": CODE_RATES.get((b >> 8) & 0x07),
         "interleave": INTERLEAVES.get(b & 0x03)},
        {"segments": _segments(_word(words, 0xF90E)),
         "modulation": _modulation(b_segments, 0),
         "code_rate": CODE_RATES.get((c >> 8) & 0x07),
         "interleave": INTERLEAVES.get(c & 0x03)},
    ]
    for layer in layers:
        if layer["segments"] == 0:
            layer["modulation"] = None
            layer["code_rate"] = None
            layer["interleave"] = None
    return Tmcc(mode, guard, partial, layers)
