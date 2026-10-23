"""AfaCmd framing for the IT9175 dongle.

Direct port of OpenDTV's ph.opendtv.source.AfaCmd. Frames are little command
packets with a 16-bit one's-complement checksum:

    build():        [len-1][class<<4][cmd][seq][count][addrlen][addr:4][data...][cs hi][cs lo]
    build_command():[len-1][cmd16 hi][cmd16 lo][seq][payload...][cs hi][cs lo]

The checksum accumulates alternating high/low bytes starting with the high byte
at index 1, then inverts the 16-bit sum.
"""

CMD_READ_REGISTERS = 0
CMD_WRITE_REGISTERS = 1

PROC_LINK = 0
PROC_OFDM = 8


def addr_len(processor, addr):
    """LINK has 8-bit addresses when possible; OFDM and larger addresses use 16-bit."""
    return 1 if processor == 0 and 0 <= addr <= 255 else 2


def checksum(frame, end):
    total = 0
    for i in range(1, end):
        b = frame[i]
        total += (b << 8) if ((i - 1) & 1) == 0 else b
    return (~total) & 0xFFFF


def finish(frame):
    cs = checksum(frame, len(frame) - 2)
    frame[-2] = (cs >> 8) & 0xFF
    frame[-1] = cs & 0xFF
    frame[0] = (len(frame) - 1) & 0xFF


def build(cmd, seq, chip, processor, addr, count, data=None):
    payload = len(data) if data else 0
    frame = bytearray(payload + 12)
    frame[1] = ((chip + processor) & 0x0F) << 4
    frame[2] = cmd & 0xFF
    frame[3] = seq & 0xFF
    frame[4] = count & 0xFF
    frame[5] = addr_len(processor, addr)
    frame[6] = (addr >> 24) & 0xFF
    frame[7] = (addr >> 16) & 0xFF
    frame[8] = (addr >> 8) & 0xFF
    frame[9] = addr & 0xFF
    if data:
        frame[10:10 + payload] = data
    finish(frame)
    return bytes(frame)


def build_read(seq, chip, processor, addr, count):
    return build(CMD_READ_REGISTERS, seq, chip, processor, addr, count, None)


def build_write(seq, chip, processor, addr, data):
    return build(CMD_WRITE_REGISTERS, seq, chip, processor, addr, len(data), data)


def build_command(cmd, seq, chip, processor, payload=None):
    payload = payload or b""
    frame = bytearray(len(payload) + 6)
    c16 = (((chip + processor) << 12) + cmd) & 0xFFFF
    frame[1] = (c16 >> 8) & 0xFF
    frame[2] = c16 & 0xFF
    frame[3] = seq & 0xFF
    if payload:
        frame[4:4 + len(payload)] = payload
    finish(frame)
    return bytes(frame)


def parse_response(resp, expect_data):
    """Return the payload, or None if the response is malformed or reports an error."""
    if len(resp) < 5 or len(resp) != expect_data + 5:
        return None
    if resp[0] != len(resp) - 1:
        return None
    if ((resp[-2] << 8) | resp[-1]) != checksum(resp, len(resp) - 2):
        return None
    if resp[2] != 0:
        return None
    return bytes(resp[3:3 + expect_data])


def status(resp):
    return resp[2] if len(resp) >= 3 else -1
