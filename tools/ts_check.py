"""Check a captured MPEG-TS: sync, PAT, PMTs, PIDs and continuity counters.

    python tools/ts_check.py capture.ts
"""
import sys
from collections import Counter


def sections(data):
    """Yield (pid, table_id, body) for complete single-packet PSI sections."""
    for i in range(0, len(data) - 187, 188):
        pkt = data[i:i + 188]
        if pkt[0] != 0x47:
            continue
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        if not (pkt[1] & 0x40):
            continue
        afc = (pkt[3] >> 4) & 3
        offset = 4
        if afc & 2:
            offset += 1 + pkt[4]
        payload = pkt[offset:]
        if not payload:
            continue
        start = 1 + payload[0]
        section = payload[start:]
        if len(section) < 3:
            continue
        length = ((section[1] & 0x0F) << 8) | section[2]
        body = section[3:3 + length - 4]
        if len(body) < length - 4:
            continue
        yield pid, section[0], body


def main(path):
    data = open(path, "rb").read()
    print("bytes %d, packets %d, trailing %d" % (len(data), len(data) // 188, len(data) % 188))

    bad = sum(1 for i in range(0, len(data) - 187, 188) if data[i] != 0x47)
    print("sync errors:", bad)

    pids = Counter()
    last_cc = {}
    cc_errors = Counter()
    for i in range(0, len(data) - 187, 188):
        pkt = data[i:i + 188]
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        pids[pid] += 1
        if (pkt[3] >> 4) & 1:
            cc = pkt[3] & 0x0F
            if pid in last_cc and pid != 0x1FFF and cc != ((last_cc[pid] + 1) & 0x0F):
                cc_errors[pid] += 1
            last_cc[pid] = cc

    pat = {}
    for pid, table_id, body in sections(data):
        if pid == 0 and table_id == 0 and not pat:
            pos = 5                      # table_id_extension(2) version section last(3)
            while pos + 4 <= len(body):
                program = (body[pos] << 8) | body[pos + 1]
                ppid = ((body[pos + 2] & 0x1F) << 8) | body[pos + 3]
                if program:
                    pat[program] = ppid
                pos += 4
    print("PAT:", {k: "0x%04x" % v for k, v in pat.items()} or "none")

    for program, pmt_pid in pat.items():
        for pid, table_id, body in sections(data):
            if pid != pmt_pid or table_id != 2:
                continue
            pcr = ((body[5] & 0x1F) << 8) | body[6]
            info_len = ((body[7] & 0x0F) << 8) | body[8]
            pos = 9 + info_len
            streams = []
            while pos + 5 <= len(body):
                stype = body[pos]
                epid = ((body[pos + 1] & 0x1F) << 8) | body[pos + 2]
                es_len = ((body[pos + 3] & 0x0F) << 8) | body[pos + 4]
                streams.append((stype, epid))
                pos += 5 + es_len
            print("program %d: PMT 0x%04x, PCR 0x%04x" % (program, pmt_pid, pcr))
            for stype, epid in streams:
                print("   stream type 0x%02x on PID 0x%04x (%d packets)"
                      % (stype, epid, pids.get(epid, 0)))
            break
        else:
            print("program %d: PMT 0x%04x not found" % (program, pmt_pid))

    print("null packets:", pids.get(0x1FFF, 0))
    print("top PIDs:", ["0x%04x:%d" % (p, c) for p, c in pids.most_common(8)])
    if cc_errors:
        print("CC errors:", {"0x%04x" % p: c for p, c in cc_errors.items()})
    else:
        print("CC errors: none")


if __name__ == "__main__":
    main(sys.argv[1])
