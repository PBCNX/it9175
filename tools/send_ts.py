"""Send a .ts file to the orchestrator's UDP input at a paced bitrate.

The pbcnx orchestrator (obs_isdbt_live.py) reads MPEG-TS from UDP 127.0.0.1:5000
and feeds the DTA-115. This tool replaces OBS/ffmpeg when the source is a
recorded capture.

    python tools/send_ts.py capture.ts --rate 9.74e6 --loop
"""
import argparse
import socket
import sys
import time

PACKET = 188
CHUNK = PACKET * 7          # 1316 bytes, a common UDP datagram size for TS


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--rate", type=float, default=9.74e6, help="bits per second")
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds")
    args = ap.parse_args(argv)

    if args.chunk % PACKET:
        raise SystemExit("--chunk must be a multiple of 188")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (args.host, args.port)
    per_chunk = args.chunk * 8.0 / args.rate
    sent = 0
    started = time.monotonic()
    next_time = started

    with open(args.file, "rb") as source:
        while True:
            block = source.read(args.chunk)
            if not block:
                if not args.loop:
                    break
                source.seek(0)
                continue
            sock.sendto(block, dest)
            sent += len(block)
            next_time += per_chunk
            delay = next_time - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:
                next_time = time.monotonic()   # fell behind; resynchronise
            if args.seconds and time.monotonic() - started >= args.seconds:
                break

    elapsed = max(time.monotonic() - started, 1e-6)
    print("sent %.1f MB in %.1f s (%.2f Mbit/s)" % (
        sent / 1e6, elapsed, sent * 8 / elapsed / 1e6), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
