"""Command line interface: list, probe, tune, play, sim."""
import argparse
import socket
import sys
import time

from . import __version__
from .device import (It9175Device, Link, SimBackend, UsbBackend, UsbError,
                     find_devices, PID_IT9175)


def log(message):
    if VERBOSE:
        print(message, file=sys.stderr, flush=True)


VERBOSE = False


def _open_device(index=0, simulate=False, tuner_type=None, firmware=None):
    if simulate:
        backend = SimBackend()
        backend.open()
        return It9175Device(Link(backend, log), log, tuner_type, firmware), backend
    devices = [d for d in find_devices() if d.idProduct == PID_IT9175]
    if not devices:
        raise SystemExit("no IT9175 dongle (048d:275a) found. Plug it in; on Windows bind it to "
                         "WinUSB with Zadig first, on Linux install the udev rule.")
    if index >= len(devices):
        raise SystemExit("only %d dongle(s) found" % len(devices))
    backend = UsbBackend(devices[index], log).open()
    return It9175Device(Link(backend, log), log, tuner_type, firmware), backend


def cmd_list(args):
    found = False
    for dev in find_devices():
        found = True
        names = {PID_IT9175: "IT9175 (supported)",
                 0x9308: "IT930x 9308 (IT9300+Sony, not this driver)",
                 0x9309: "IT930x 9309 (IT930x, not this driver)"}
        print("048d:%04x  bus %s addr %s  %s" % (
            dev.idProduct, dev.bus, dev.address,
            names.get(dev.idProduct, "unknown/unsupported")))
        try:
            for cfg in dev:
                for intf in cfg:
                    for ep in intf:
                        print("    intf %d alt %d  ep 0x%02x  attr 0x%02x  max %d" % (
                            intf.bInterfaceNumber, intf.bAlternateSetting,
                            ep.bEndpointAddress, ep.bmAttributes, ep.wMaxPacketSize))
        except Exception as exc:
            print("    descriptors: %s" % exc)
    if not found:
        print("no 048d devices found")
        return 0
    return 0


def cmd_probe(args):
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    try:
        if not device.init():
            print("init failed", file=sys.stderr)
            print("\n".join(device.notes), file=sys.stderr)
            return 2
        report = device.probe_report()
        print(report)
        if args.freq:
            print("tune:", "locked" if device.tune(args.freq) else "no lock")
            print(device.status())
        return 0
    finally:
        backend.close()


def cmd_tune(args):
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    try:
        if not device.init():
            print("init failed", file=sys.stderr)
            print("\n".join(device.notes), file=sys.stderr)
            return 2
        locked = device.tune(args.freq)
        status = device.status()
        print("freq %d kHz: %s" % (args.freq, "LOCKED" if locked else "NO LOCK"))
        if status:
            print("strength %s%% (raw %s)  quality %s%%  snr %s  dbm %s  ber %s/%s" % (
                status["strength_percent"], status["raw_strength"], status["quality_percent"],
                status["raw_snr"], status["dbm"], status["ber_errors"], status["ber_window"]))
        return 0 if locked else 1
    finally:
        backend.close()


class TsSink:
    def __init__(self, path=None, udp=None):
        self.file = None
        self.sock = None
        self.addr = None
        if udp:
            host, _, port = udp.rpartition(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addr = (host or "127.0.0.1", int(port))
        elif path and path != "-":
            self.file = open(path, "wb")
        else:
            self.file = sys.stdout.buffer

    def write(self, data):
        if self.sock:
            for i in range(0, len(data), 1316):
                self.sock.sendto(data[i:i + 1316], self.addr)
        else:
            self.file.write(data)
            self.file.flush()

    def close(self):
        if self.file and self.file is not sys.stdout.buffer:
            self.file.close()
        if self.sock:
            self.sock.close()


def cmd_play(args):
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    sink = TsSink(args.out, args.udp)
    started = time.time()
    packets = 0
    try:
        if not device.init():
            print("init failed", file=sys.stderr)
            print("\n".join(device.notes), file=sys.stderr)
            return 2
        device.tune(args.freq)
        if args.status_interval:
            last = time.time()
        print("streaming from %d kHz to %s (Ctrl-C to stop)" % (
            args.freq, args.udp or args.out or "stdout"), file=sys.stderr)
        while True:
            if args.seconds and time.time() - started >= args.seconds:
                break
            try:
                data = device.read_ts()
            except Exception as exc:
                if args.verbose:
                    print("read: %s" % exc, file=sys.stderr)
                time.sleep(0.2)
                continue
            if not data:
                continue
            sink.write(data)
            packets += len(data) // 188
            if args.status_interval and time.time() - last >= args.status_interval:
                last = time.time()
                st = device.status() or {}
                print("ts packets %d  lock %s  strength %s  quality %s" % (
                    packets, st.get("locked"), st.get("strength_percent"), st.get("quality_percent")),
                    file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        backend.close()
    return 0


def cmd_scan(args):
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    try:
        if not device.init():
            print("init failed", file=sys.stderr)
            print("\n".join(device.notes), file=sys.stderr)
            return 2
        found = 0
        total = 0
        for freq in range(args.start, args.stop + 1, args.step):
            total += 1
            locked = device.tune(freq, quick=True)
            status = device.status() or {}
            print("%7d kHz  %-7s strength %3s  quality %3s  dbm %4s" % (
                freq, "LOCK" if locked else "no lock",
                status.get("strength_percent"), status.get("quality_percent"),
                status.get("dbm")), flush=True)
            if locked:
                found += 1
        print("%d/%d locked" % (found, total))
        return 0 if found else 1
    finally:
        backend.close()


def cmd_sim(args):
    backend = SimBackend()
    backend.open()
    device = It9175Device(Link(backend, print), print)
    ok = device.init()
    print("init:", ok)
    if not ok:
        print("\n".join(device.notes))
        return 1
    locked = device.tune(599143)
    print("lock:", locked, device.status())
    data = device.read_ts(16356)
    print("ts bytes:", len(data), "sync:", hex(data[0]) if data else None)
    chunks = sum(1 for c in backend.commands if c == 41)
    print("firmware: %d bytes in %d chunks, commands=%d%s" % (
        backend.firmware_bytes, chunks, len(backend.commands),
        " (zeros: vendor image not read)" if device.firmware_simulated else ""))
    return 0 if locked and data[:1] == b"\x47" else 1


def main(argv=None):
    global VERBOSE
    parser = argparse.ArgumentParser(prog="it9175", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="log USB traffic")
    parser.add_argument("--firmware", metavar="PATH",
                        help="IT9175 firmware image (default: $IT9175_FIRMWARE or "
                             "it9175/firmware.bin)")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list 048d devices")
    p.set_defaults(func=cmd_list)

    for name, func, help_text in (
        ("probe", cmd_probe, "open, initialise and report"),
        ("tune", cmd_tune, "tune one frequency"),
        ("play", cmd_play, "stream MPEG-TS"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--index", type=int, default=0, help="which dongle if several")
        p.add_argument("--sim", action="store_true", help="use the fake device (no hardware)")
        p.add_argument("--tuner-type", type=int, choices=(0, 1), default=None,
                       help="override the tuner type read from the chip")
        p.set_defaults(func=func)
        if name in ("probe", "tune", "play"):
            p.add_argument("--freq", type=int, default=None if name == "probe" else 599143,
                           help="frequency in kHz")
        if name == "play":
            p.add_argument("--out", default="-", help="output file, - for stdout")
            p.add_argument("--udp", help="send TS to HOST:PORT instead of a file")
            p.add_argument("--seconds", type=float, default=0, help="stop after N seconds")
            p.add_argument("--status-interval", type=float, default=5.0,
                           help="print signal status every N seconds (0 to disable)")

    p = sub.add_parser("scan", help="scan a frequency range")
    p.add_argument("--index", type=int, default=0, help="which dongle if several")
    p.add_argument("--sim", action="store_true", help="use the fake device (no hardware)")
    p.add_argument("--tuner-type", type=int, choices=(0, 1), default=None,
                   help="override the tuner type read from the chip")
    p.add_argument("--start", type=int, default=473143, help="first frequency in kHz")
    p.add_argument("--stop", type=int, default=695143, help="last frequency in kHz")
    p.add_argument("--step", type=int, default=6000, help="step in kHz")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("sim", help="run the protocol against a fake device")
    p.set_defaults(func=cmd_sim)

    args = parser.parse_args(argv)
    VERBOSE = args.verbose
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
