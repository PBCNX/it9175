"""Read-only preflight: can this machine talk to an IT9175 dongle?

Checks the environment and enumerates 048d devices without claiming or writing
anything. Run it before the first real run on a new machine:

    python tools/preflight.py

Exit codes:
    0  an IT9175 (048d:275a) is visible
    1  environment is fine, but no 275a is attached
    2  environment is broken (pyusb, libusb backend, vendored tree missing)
    3  unexpected error
"""
import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from it9175 import device  # noqa: E402  (path set above)


def line(label, value):
    print("%-10s %s" % (label + ":", value))


def main():
    line("platform", platform.platform())
    line("machine", platform.machine())
    line("python", sys.version.split()[0])

    vendor = os.path.join(ROOT, "vendor")
    line("vendor", "present" if os.path.isdir(os.path.join(vendor, "usb")) else "MISSING")

    if os.name == "nt":
        dll = os.path.join(ROOT, "vendor", "windows", "x64", "libusb-1.0.dll")
        line("libusb", "bundled" if os.path.exists(dll) else "not bundled (will search PATH)")
        line("driver", "bind 048d:275a to WinUSB with Zadig before claiming")
    elif sys.platform == "darwin":
        line("libusb", "system (install it: brew install libusb)")
        line("driver", "none needed; macOS has no IT9175 driver to detach")
    else:
        rule = "/etc/udev/rules.d/99-it9175.rules"
        line("udev", "installed" if os.path.exists(rule) else "not installed (%s)" % rule)
        line("driver", "userspace; no kernel driver is involved")

    try:
        device._ensure_pyusb()
        import usb
        line("pyusb", getattr(usb, "__version__", "?"))
    except Exception as exc:
        line("pyusb", "FAILED: %s" % exc)
        print("\nverdict   : ENVIRONMENT BROKEN (pyusb unavailable)")
        return 2

    try:
        backend = device._load_backend()
    except Exception as exc:
        line("backend", "FAILED: %s" % exc)
        print("\nverdict   : ENVIRONMENT BROKEN (libusb backend error)")
        return 2

    if backend is None:
        line("backend", "NONE")
        if sys.platform == "darwin":
            print("          try: brew install libusb")
            print("          or:  IT9175_LIBUSB=/opt/homebrew/lib/libusb-1.0.dylib python tools/preflight.py")
        print("\nverdict   : ENVIRONMENT BROKEN (no libusb backend)")
        return 2

    libname = getattr(getattr(backend, "lib", None), "_name", "?")
    line("backend", "ok (%s)" % libname)

    fw = os.environ.get("IT9175_FIRMWARE") or os.path.join(ROOT, "it9175", "firmware.bin")
    line("firmware", "present" if os.path.exists(fw) else "absent (needed for a real run, not for --sim)")

    try:
        devices = device.find_devices()
    except Exception as exc:
        line("devices", "FAILED: %s" % exc)
        print("\nverdict   : ENVIRONMENT BROKEN (enumeration failed)")
        return 2

    if not devices:
        print("\nverdict   : NO 048D DEVICE (plug the dongle; on Windows bind it with Zadig)")
        return 1

    found = False
    for dev in devices:
        pid = dev.idProduct
        print("\n%04x:%04x  bus %s addr %s  %s" % (
            dev.idVendor, pid, dev.bus, dev.address,
            device.DEVICE_NAMES.get(pid, "unknown/unsupported")))
        try:
            for cfg in dev:
                for intf in cfg:
                    eps = ["0x%02x" % ep.bEndpointAddress for ep in intf]
                    print("  intf %d alt %d  %s" % (
                        intf.bInterfaceNumber, intf.bAlternateSetting, " ".join(eps) or "no endpoints"))
        except Exception as exc:
            print("  descriptors: %s" % exc)
        if pid == device.PID_IT9175:
            found = True

    if not found:
        print("\nverdict   : NO IT9175 (048d:275a) - other 048d devices are not this driver")
        return 1

    print("\nverdict   : READY - IT9175 visible; next: python -m it9175 probe --freq 599143")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # keep the exit code contract
        print("\nverdict   : UNEXPECTED ERROR: %s" % exc)
        sys.exit(3)
