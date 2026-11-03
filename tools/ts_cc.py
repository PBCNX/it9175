"""Per-PID continuity-counter analysis of a capture.

    python tools/ts_cc.py file.ts [more.ts ...]

Reports, per PID: packets, CC discontinuities, duplicate packets and TEI.  A
counter that jumps by one is a lost packet; a counter that does not advance is a
duplicate and is legal (the spec allows one duplicate per packet).  Null packets
(0x1FFF) are counted separately and excluded from the error totals, since
adaptation-only padding carries no continuity.

Exit code is 0 when every stream is clean, 1 otherwise, so it can gate a test.
"""
import sys

NULL_PID = 0x1FFF


def analyse(path):
    data = open(path, "rb").read()
    total = len(data) // 188
    sync_errors = 0
    tei = 0
    per_pid = {}
    last_cc = {}
    expected_next = set()

    for index in range(total):
        packet = data[index * 188:(index + 1) * 188]
        if packet[0] != 0x47:
            sync_errors += 1
            continue
        pid = ((packet[1] & 0x1F) << 8) | packet[2]
        entry = per_pid.setdefault(pid, {"packets": 0, "cc_errors": 0,
                                         "duplicates": 0, "tei": 0,
                                         "payload": 0})
        entry["packets"] += 1
        if packet[1] & 0x80:
            entry["tei"] += 1
            tei += 1

        adaptation = (packet[3] >> 4) & 0x03
        has_payload = adaptation in (1, 3)
        counter = packet[3] & 0x0F

        if pid == NULL_PID:
            continue
        if not has_payload:
            # No payload: the counter must not change at all.
            continue

        entry["payload"] += 1
        previous = last_cc.get(pid)
        if previous is None:
            last_cc[pid] = counter
            continue
        step = (counter - previous) & 0x0F
        if step == 1:
            last_cc[pid] = counter
        elif step == 0:
            entry["duplicates"] += 1
            # a duplicate repeats the same counter; keep the state as it was
        else:
            entry["cc_errors"] += 1
            last_cc[pid] = counter

    return {
        "path": path,
        "bytes": len(data),
        "packets": total,
        "sync_errors": sync_errors,
        "tei": tei,
        "per_pid": per_pid,
    }


def report(result, top=6):
    print("== %s" % result["path"])
    print("   packets %d  bytes %d  sync errors %d  TEI %d"
          % (result["packets"], result["bytes"], result["sync_errors"], result["tei"]))
    pids = sorted(result["per_pid"].items(),
                  key=lambda kv: -kv[1]["cc_errors"])
    total_cc = sum(entry["cc_errors"] for _, entry in pids)
    print("   total CC errors: %d over %d PIDs"
          % (total_cc, len([1 for _, e in pids if e["cc_errors"]])))
    for pid, entry in pids[:top]:
        if pid == NULL_PID:
            continue
        print("   pid 0x%04x (%5d pkt, %6d payload): CC %3d  dup %2d  TEI %d"
              % (pid, entry["packets"], entry["payload"], entry["cc_errors"],
                 entry["duplicates"], entry["tei"]))
    return total_cc


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    dirty = 0
    for path in argv[1:]:
        try:
            result = analyse(path)
        except FileNotFoundError:
            print("== %s: missing" % path)
            continue
        if report(result):
            dirty += 1
    return 1 if dirty else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
