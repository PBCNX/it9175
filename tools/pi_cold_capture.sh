#!/bin/bash
# Cold-plug capture of a DiBcom S870 (10b8:1fa0): everything from power-on to TS.
#
# The previous capture started after the driver had probed the stick, so it held
# neither the firmware download nor the demod power-up - the two steps a
# user-space driver cannot guess.  This one starts capturing first and asks you
# to plug the stick in.
#
#   ./pi_cold_capture.sh [frequency_khz]
#
# usbmon0 captures every bus, so it does not matter which port the stick is in.
#
# It writes three files next to each other in ~/captures:
#   cold.pcap       the USB traffic (what we came for)
#   cold-dmesg.txt  what dib0700 said: cold state, firmware started, version
#   cold-lsusb.txt  the descriptor set after the firmware is running
set -u

FREQ="${1:-509143}"
OUT="$HOME/captures"
mkdir -p "$OUT"

cat > "$OUT/isdbt.conf" <<EOF
[$FREQ]
DELIVERY_SYSTEM = ISDBT
FREQUENCY = ${FREQ}000
BANDWIDTH_HZ = 6000000
EOF

for tool in lsusb tcpdump dvbv5-zap; do
    command -v "$tool" >/dev/null || { echo "missing: $tool"; exit 1; }
done

# A capture of a stick that is already warm tells us nothing, so say so loudly.
if lsusb -d 10b8:1fa0 >/dev/null 2>&1; then
    echo "WARNING: the S870 is already plugged in - unplug it before starting."
    read -r -p "         Unplug it and press Enter... " _
fi

ls -l /lib/firmware/dvb-usb-dib0700-1.20.fw 2>/dev/null \
    || echo "WARNING: firmware missing from /lib/firmware - copy it there first"

sudo modprobe dvb_usb_dib0700 2>/dev/null || true
sudo modprobe usbmon || { echo "cannot load usbmon"; exit 1; }

echo
echo "Starting capture on usbmon0 (all buses)."
sudo tcpdump -i usbmon0 -s 0 -U -w "$OUT/cold.pcap" 2>/dev/null &
PID=$!
sleep 1

echo
echo ">>> Plug the S870 in now."
read -r -p "    Press Enter once it is attached and the firmware has loaded (~10 s)... " _

echo "Running dvbv5-zap for ${FREQ} kHz..."
timeout 20 dvbv5-zap -a 0 -c "$OUT/isdbt.conf" "$FREQ" -r >/dev/null 2>&1 || true
sleep 1

sudo kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true

# The driver's own account: did it see a cold device, did the firmware start,
# which version did it read, did anything re-enumerate?
dmesg --ctime 2>/dev/null | tail -n 120 > "$OUT/cold-dmesg.txt" \
    || dmesg | tail -n 120 > "$OUT/cold-dmesg.txt"
lsusb -v -d 10b8:1fa0 > "$OUT/cold-lsusb.txt" 2>&1 || true

echo
ls -l "$OUT/cold.pcap" "$OUT/cold-dmesg.txt" "$OUT/cold-lsusb.txt"
grep -Ei "cold|firmware|dib0700|10b8" "$OUT/cold-dmesg.txt" | tail -n 20
echo
echo "Copy all three to the PC, into D:\\Profile\\Documents\\DeepSeek\\sticks\\.tmp\\ :"
echo "  scp pi@<this-pi>:~/captures/cold-*.txt pi@<this-pi>:~/captures/cold.pcap ."
