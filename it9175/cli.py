"""Command line interface: list, probe, tune, tmcc, recover, reboot, play, scan, sim."""
import argparse
import queue
import socket
import sys
import threading
import time

from . import PROVENANCE, __version__
from .supervisor import wait_for_device
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


def cmd_tmcc(args):
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    try:
        if not device.init():
            print("init failed", file=sys.stderr)
            print("\n".join(device.notes), file=sys.stderr)
            return 2
        if args.freq:
            device.tune(args.freq)
        report = device.tmcc_settled()
        # Two refusals, both honest and different: None means no two consecutive valid readings ever
        # agreed (transient after a switch, or an undecoded block); invalid means a single reading
        # that describes no channel (the 0x0000 ghost).
        if report is None:
            print("%d kHz tmcc did not settle (no two consecutive valid readings agreed - a switch "
                  "leaves TMCC transient, or the demod has not decoded it)" % (args.freq or 0))
            return 1
        if args.json:
            import json
            print(json.dumps(report.as_dict(), indent=1))
        elif not report.valid:
            print("%d kHz tmcc not decoded yet (mode/guard/layers unreadable - the demod has not "
                  "decoded TMCC on this channel)" % (args.freq or 0))
        else:
            print("%d kHz tmcc %s" % (args.freq or 0, report))
        return 0 if report.valid else 1
    finally:
        backend.close()


def _endpoint(args):
    """Where the dongle is now: 'bus N addr M', 'absent', or 'simulated'."""
    if getattr(args, "sim", False):
        return "simulated"
    try:
        devices = [d for d in find_devices() if d.idProduct == PID_IT9175]
        if not devices:
            return "absent"
        device = devices[0]
        return "bus %s addr %s" % (device.bus, device.address)
    except Exception as exc:
        return "unreadable (%s)" % exc


def _firmware(device):
    """The LINK firmware version, or what stopped us reading it - the other half of the pair."""
    try:
        value = device.link.fw_version(0)
        return value.hex(" ") if value else "none"
    except Exception as exc:
        return "unreadable (%s)" % exc


def _report(device, args, label):
    print("%s: %s, firmware LINK=%s" % (label, _endpoint(args), _firmware(device)),
          file=sys.stderr)


def cmd_recover(args):
    """Recover a stuck session: warm re-init, then (if needed) a forced boot-ROM reset.

    Measured on hardware 2026-11-20: writing the pre-upload sequence to a **running** chip wipes
    its image and makes the device re-enumerate - the USB handle dies mid-attempt, so the upload
    must happen over a fresh handle. Hence two phases: a safe warm re-init first (which is enough
    for the warm-re-open flake), and only then force_boot(), wait for the device to come back,
    re-open it and let init() upload. If it never comes back, the cable is the answer and the
    message says so.
    """
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    try:
        endpoint_before = _endpoint(args)
        firmware_before = _firmware(device)
        _report(device, args, "before")
        if not getattr(args, "force", False) and device.recover():
            print("recovered: warm bring-up ok")
            _report(device, args, "after (warm)")
            return _recover_tune(device, args)
        print("warm bring-up failed; forcing the pre-upload sequence (the device may re-enumerate)",
              file=sys.stderr)
        device.force_boot()
    except Exception as exc:
        print("force_boot: %s" % exc, file=sys.stderr)
    finally:
        try:
            backend.close()
        except Exception:
            pass

    deadline = time.time() + args.wait
    attempt = 0
    last_error = None
    while time.time() < deadline:
        time.sleep(0.5)
        attempt += 1
        try:
            device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
        except SystemExit as exc:
            last_error = str(exc)
            continue
        try:
            if device.init():
                endpoint_after = _endpoint(args)
                firmware_after = _firmware(device)
                if endpoint_after != endpoint_before:
                    how = "re-enumeration"
                else:
                    how = "re-open, same address"
                if firmware_after != firmware_before:
                    outcome = "image rebuilt (%s -> %s)" % (firmware_before, firmware_after)
                else:
                    outcome = "image preserved (%s)" % firmware_after
                print("recovered: forced bring-up after %s (attempt %d); %s"
                      % (how, attempt, outcome))
                _report(device, args, "after (cold)")
                for line in device.notes:
                    if ("firmware" in line or "cold start" in line
                            or "chip version" in line or "fw LINK" in line):
                        print("  " + line)
                return _recover_tune(device, args)
        except Exception as exc:
            last_error = str(exc)
        finally:
            try:
                backend.close()
            except Exception:
                pass
    print("recover failed: the device did not come back within %d s%s. Unplug and replug the "
          "stick - a USB reset does not clear its state."
          % (args.wait, (": " + last_error) if last_error else ""), file=sys.stderr)
    return 1


def _recover_tune(device, args):
    if args.freq:
        locked = device.tune(args.freq)
        print("%d kHz: %s" % (args.freq, "LOCKED" if locked else "NO LOCK"))
        if not locked:
            return 1
    return 0


def cmd_reboot(args):
    """The vendor SDK's `Cmd_reboot`, as close as the interface allows.

    No distinct reboot opcode exists - not in the vendor capture (only 0x00, 0x01, 0x04, 0x29,
    0x2b) and not in a payload-less sweep of 0x20-0x2F (the firmware version never blanked). What
    the SDK can be doing is the pre-upload register sequence, which this driver already has as
    `force_boot()`. So `reboot` is that same sequence forced first, then the re-enumerated device
    is re-opened and the firmware uploaded - the same path `recover` takes when its warm attempt
    fails, without the warm attempt.
    """
    args.force = True
    return cmd_recover(args)


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


def strip_null_packets(data):
    """Drop whole MPEG-TS null packets (PID 0x1FFF); keep anything unaligned."""
    if not data:
        return data
    out = bytearray()
    full = len(data) - (len(data) % 188)
    for offset in range(0, full, 188):
        pid = ((data[offset + 1] & 0x1F) << 8) | data[offset + 2]
        if data[offset] == 0x47 and pid == 0x1FFF:
            continue
        out += data[offset:offset + 188]
    if full < len(data):
        out += data[full:]
    return bytes(out)


class TsSink:
    """Writes TS on its own thread, so a slow consumer cannot stall USB reads.

    Lossless mode (default) blocks when the bounded queue is full: captures keep
    every byte, order preserved. Live mode drops the oldest chunk instead, for
    players that would rather lose a little than pause the dongle.
    """

    def __init__(self, path=None, udp=None, drop_null=False, live=False, queue_size=64):
        self.file = None
        self.sock = None
        self.addr = None
        self.drop_null = drop_null
        self.live = live
        self.dropped = 0
        self.queue = queue.Queue(maxsize=max(1, queue_size))
        if udp:
            host, _, port = udp.rpartition(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addr = (host or "127.0.0.1", int(port))
        elif path and path != "-":
            self.file = open(path, "wb")
        else:
            self.file = sys.stdout.buffer
        self.thread = threading.Thread(target=self._run, name="it9175-sink", daemon=True)
        self.thread.start()

    def write(self, data):
        if self.drop_null:
            data = strip_null_packets(data)
        if not data:
            return
        if not self.live:
            self.queue.put(data)          # lossless: backpressure only if the
            return                        # consumer cannot keep up for long
        while True:
            try:
                self.queue.put_nowait(data)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass

    def _run(self):
        while True:
            data = self.queue.get()
            if data is None:
                return
            try:
                self._emit(data)
            except Exception:
                # A dead stdout/socket must not hang the producer; keep draining.
                pass

    def _emit(self, data):
        if self.sock:
            for i in range(0, len(data), 1316):
                self.sock.sendto(data[i:i + 1316], self.addr)
        else:
            self.file.write(data)
            self.file.flush()

    def close(self):
        if self.thread.is_alive():
            if self.live:
                while True:
                    try:
                        self.queue.put_nowait(None)
                        break
                    except queue.Full:
                        try:
                            self.queue.get_nowait()
                            self.dropped += 1
                        except queue.Empty:
                            pass
            else:
                self.queue.put(None)
            self.thread.join()
        if self.file and self.file is not sys.stdout.buffer:
            self.file.close()
        if self.sock:
            self.sock.close()


def _rebuild(args, freq):
    """Re-open, bring up and re-tune on whatever dongle is present (the attach supervisor)."""
    def open_fn():
        try:
            device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
        except SystemExit as exc:          # no matching USB id yet
            raise OSError(str(exc))
        try:
            if not device.init():
                raise RuntimeError("bring-up failed")
            if device.tune(freq):
                return device, backend
            # A warm bring-up can leave the demod suspended: resident firmware does not mean a
            # running chip, and only the upload restarts its CPU (measured 2026-11-22: after a
            # replug the warm path read strength 100 / snr 0.0 and never locked; a forced upload
            # on the same handle locked in 1224 ms). Close first - a forced upload over a running
            # chip wedges this device - then bring it up cold and retry the tune once.
            backend.close()
            device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
            if not device.init(cold=True):
                raise RuntimeError("cold bring-up failed")
            if not device.tune(freq):
                raise RuntimeError("no lock after a cold bring-up at %d kHz" % freq)
        except Exception:
            try:
                backend.close()
            except Exception:
                pass
            raise
        return device, backend

    # wait_for_device returns None when the budget is spent; normalise to a pair so the
    # caller can unpack unconditionally (a traceback here would destroy the replug message,
    # which is the whole point of the failure path).
    return wait_for_device(open_fn, attempts=int(args.supervise_seconds / 0.5), delay_s=0.5,
                           log=lambda line: print(line, file=sys.stderr)) or (None, None)


_PLAY_START = None


def _stamp():
    """Seconds since the run started - the timestamp the family standard asks for."""
    if _PLAY_START is None:
        return ""
    return "[+%6.1fs] " % (time.time() - _PLAY_START)


def _lost_device(args, backend, reason):
    """Close the dead handle and wait for the device; returns (device, backend) or (None, None)."""
    print("%sstream lost (%s); waiting for the dongle to come back" % (_stamp(), reason),
          file=sys.stderr)
    try:
        backend.close()
    except Exception:
        pass
    rebuilt = _rebuild(args, args.freq)
    if not rebuilt:
        print("dongle did not come back in %ds: unplug and replug it (a USB reset does not "
              "clear its state)" % args.supervise_seconds, file=sys.stderr)
        return None, None
    device, backend = rebuilt
    if device is None:
        print("dongle did not come back in %ds: unplug and replug it (a USB reset does not "
              "clear its state)" % args.supervise_seconds, file=sys.stderr)
        return None, None
    print("%srebuilt: %d kHz again" % (_stamp(), args.freq), file=sys.stderr)
    if hasattr(device, "link"):              # tests hand in a stub; real sessions always have one
        _report(device, args, "stream")      # same pair on the new handle, so the log says which handle
    return device, backend


def _device_present():
    """Is a 048d:275a dongle on the bus right now? (A pull may not raise on the read.)"""
    try:
        return any(device.idProduct == PID_IT9175 for device in find_devices())
    except Exception:
        return False


def cmd_play(args):
    device, backend = _open_device(args.index, args.sim, args.tuner_type, args.firmware)
    sink = TsSink(args.out, args.udp, args.drop_null, args.live)
    global _PLAY_START
    started = time.time()
    _PLAY_START = started
    packets = 0
    last_packets = 0
    hinted = False
    last_data = time.time()
    recoveries = 0
    try:
        if not device.init():
            print("init failed", file=sys.stderr)
            print("\n".join(device.notes), file=sys.stderr)
            return 2
        device.tune(args.freq)
        _report(device, args, "device")       # the pair is in the log of every run that may recover
        if args.status_interval:
            last = time.time()
        print("%sstreaming from %d kHz to %s (Ctrl-C to stop)" % (_stamp(),
            args.freq, args.udp or args.out or "stdout"), file=sys.stderr)
        switched = False
        before_zap = 0
        switch_due = started + max(0.0, args.switch_after)
        while True:
            if args.seconds and time.time() - started >= args.seconds:
                break
            if args.switch_to and not switched and time.time() >= switch_due:
                switched = True
                before_zap = packets
                began = time.time()
                locked = device.tune(args.switch_to)
                elapsed = (time.time() - began) * 1000.0
                # The reader is NOT restarted: the live-handle shape. The next read either
                # continues the same pipe or proves it did not - that is the measurement.
                print("%szap %d kHz: %.0f ms lock=%s  packets before=%d (reader untouched)"
                      % (_stamp(), args.switch_to, elapsed, locked, before_zap), file=sys.stderr)
                args.freq = args.switch_to
                last_data = time.time()
                continue
            try:
                data = device.read_ts()
            except Exception as exc:
                if args.verbose:
                    print("read: %s" % exc, file=sys.stderr)
                if not args.supervise:
                    time.sleep(0.2)
                    continue
                device, backend = _lost_device(args, backend, exc)
                if device is None:
                    return 2
                last_data = time.time()
                continue
            if not data:
                if (args.supervise and time.time() - last_data > args.stall_seconds
                        and not _device_present()):
                    device, backend = _lost_device(
                        args, backend, "silent %.1fs and the dongle is gone"
                        % (time.time() - last_data))
                    if device is None:
                        return 2
                    last_data = time.time()
                continue
            last_data = time.time()
            sink.write(data)
            packets += len(data) // 188
            if args.status_interval and time.time() - last >= args.status_interval:
                st = device.status() or {}
                if st.get("locked") and packets == last_packets and recoveries < args.recover_tries:
                    recoveries += 1
                    print("%sstate 3: locked but no TS data; rebuilding the session (%d/%d)"
                          % (_stamp(), recoveries, args.recover_tries), file=sys.stderr)
                    device, backend = _lost_device(args, backend, "locked, no TS data")
                    if device is None:
                        return 2
                    last = time.time()
                    continue
                if st.get("locked") and packets == last_packets and not hinted:
                    hinted = True
                    print("state 3 failed after %d rebuild(s): unplug and replug the stick "
                          "(a USB reset does not clear this device)." % recoveries, file=sys.stderr)
                last_packets = packets
                last = time.time()
                print("ts packets %d%s  lock %s  strength %s  quality %s" % (
                    packets,
                    (" (since zap %d)" % (packets - before_zap)) if switched else "",
                    st.get("locked"), st.get("strength_percent"),
                    st.get("quality_percent")),
                    file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sink.close()
        except Exception as exc:
            print("sink close: %s" % exc, file=sys.stderr)
        if sink.dropped:
            print("sink: dropped %d stale chunk(s) (live mode)" % sink.dropped, file=sys.stderr)
        if backend is not None:                # a failed recovery hands back (None, None)
            try:
                backend.close()                # may already be closed by a recovery path
            except Exception as exc:
                print("transport close: %s" % exc, file=sys.stderr)
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
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__ + " (" + PROVENANCE + ")")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list 048d devices")
    p.set_defaults(func=cmd_list)

    for name, func, help_text in (
        ("probe", cmd_probe, "open, initialise and report"),
        ("tune", cmd_tune, "tune one frequency"),
        ("tmcc", cmd_tmcc, "show the TMCC transmission parameters"),
        ("recover", cmd_recover, "cold-start the chip after a stuck session"),
        ("reboot", cmd_reboot, "force the boot ROM and bring the chip back up"),
        ("play", cmd_play, "stream MPEG-TS"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--index", type=int, default=0, help="which dongle if several")
        p.add_argument("--sim", action="store_true", help="use the fake device (no hardware)")
        p.add_argument("--tuner-type", type=int, choices=(0, 1), default=None,
                       help="override the tuner type read from the chip")
        p.set_defaults(func=func)
        if name in ("probe", "tune", "tmcc", "recover", "reboot", "play"):
            p.add_argument("--freq", type=int, default=None if name == "probe" else 599143,
                           help="frequency in kHz")
        if name in ("recover", "reboot"):
            p.add_argument("--wait", type=float, default=15.0,
                           help="seconds to wait for the device to re-enumerate (default 15)")
        if name == "recover":
            p.add_argument("--force", action="store_true",
                           help="skip the warm attempt and force the boot-ROM reset")
        if name in ("tmcc", "play"):
            p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "play":
            p.add_argument("--out", default="-", help="output file, - for stdout")
            p.add_argument("--udp", help="send TS to HOST:PORT instead of a file")
            p.add_argument("--seconds", type=float, default=0, help="stop after N seconds")
            p.add_argument("--drop-null", action="store_true",
                           help="drop MPEG-TS null packets (PID 0x1FFF) for slow consumers")
            p.add_argument("--live", action="store_true",
                           help="drop stale chunks instead of stalling USB when the consumer is slow")
            p.add_argument("--status-interval", type=float, default=5.0,
                           help="print signal status every N seconds (0 to disable)")
            p.add_argument("--no-supervise", dest="supervise", action="store_false",
                           help="do not rebuild the session when the dongle is unplugged")
            p.add_argument("--switch-to", type=int, metavar="KHZ",
                           help="change channel on the live handle after --switch-after seconds "
                                "(a fast zap: the reader is NOT restarted)")
            p.add_argument("--switch-after", type=float, default=2.0, metavar="SEC",
                           help="seconds before --switch-to fires (default 2)")
            p.add_argument("--supervise-seconds", type=float, default=30.0,
                           help="how long to wait for the dongle to come back (default 30)")
            p.add_argument("--stall-seconds", type=float, default=2.0,
                           help="silent-stream window before checking the bus (default 2)")
            p.add_argument("--recover-tries", type=int, default=3,
                           help="automatic session rebuilds for a locked, silent stream (0 disables)")

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
    try:
        return args.func(args)
    except UsbError as exc:
        # The first command a reader runs must fail like a program, not like a crash: no libusb and no dongle are
        # ordinary states, and a traceback reads as our bug even when it is their machine (audit 2026-11-24, M3).
        print("it9175: %s" % exc, file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        # The firmware file is a user-supplied input, so a missing one is an ordinary state too (audit 2026-11-24, B11).
        print("it9175: %s" % exc, file=sys.stderr)
        return 2
    except ValueError as exc:
        # A firmware image that is not the right one raises ValueError from the size/SHA-256 check.
        print("it9175: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
