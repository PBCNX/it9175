#!/bin/bash
# Capture the Siano Rio and DiBcom S870 bring-up on a Linux host.
# Run as a normal user; sudo is used for usbmon/tcpdump.
set -u

OUT="$HOME/captures"
mkdir -p "$OUT"

cat > "$OUT/isdbt.conf" <<'EOF'
[599143]
DELIVERY_SYSTEM = ISDBT
FREQUENCY = 599143000
BANDWIDTH_HZ = 6000000
EOF

need() { command -v "$1" >/dev/null || { echo "missing: $1"; exit 1; }; }
need lsusb
need tcpdump
need dvbv5-zap

capture() {
    local name="$1" vidpid="$2" module="$3"
    echo "== $name ($vidpid)"
    lsusb -d "$vidpid" || { echo "  not attached"; return; }
    local bus
    bus=$(lsusb -d "$vidpid" | sed -E 's/^Bus ([0-9]+).*/\1/' | head -1)
    echo "  bus $bus"
    sudo modprobe "$module" || true
    sudo modprobe usbmon || true
    sudo tcpdump -i "usbmon$bus" -w "$OUT/$name.pcap" 2>/dev/null &
    local pid=$!
    sleep 2
    timeout 12 dvbv5-zap -a 0 -c "$OUT/isdbt.conf" 599143 -r >/dev/null 2>&1 || true
    sleep 1
    sudo kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    ls -l "$OUT/$name.pcap"
}

echo "firmware:"
ls -l /lib/firmware/isdbt_rio.inp /lib/firmware/dvb-usb-dib0700-1.20.fw 2>/dev/null || true

# Attach one stick at a time.
capture siano 187f:0600 smsusb
capture s870  10b8:1fa0 dvb_usb_dib0700

echo "done: $OUT/*.pcap"
