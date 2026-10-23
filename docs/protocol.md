# IT9175 USB protocol (`048d:275a`)

What the driver actually puts on the wire, and why. Every statement here was
read out of `it9175/afa.py`, `it9175/device.py` and `it9175/tuner.py` (the code
*is* the specification; this file explains it). The few bench measurements are
dated where they appear. Nothing is inferred from a sibling chipset.

## 1. Endpoints

| Endpoint | Direction | Transfer | Use |
|---|---|---|---|
| `0x02` | OUT | bulk | command frames |
| `0x81` | IN | bulk | one response per command, read as 256 B |
| `0x84` | IN | bulk | MPEG-TS, read as 16,356 B = 87 × 188 |

One vendor-specific interface carrying all three endpoints; no alternate
setting is selected. The device is bound to WinUSB/libusb, and the driver
detaches a kernel driver if one is attached. `UsbBackend.open()` claims every
interface that carries one of the three endpoints and refuses a device missing
any of them by name.

## 2. Framing

There are two frame families. Both end in a 16-bit checksum, both start with
`length - 1`, and both carry a sequence byte modulo 256.

### Register access (`afa.build`, commands 0 and 1)

```
+0   length - 1
+1   ((chip + processor) & 0x0F) << 4      chip is always 0 here: processor << 4
+2   command: 0 = read registers, 1 = write registers
+3   sequence & 0xFF
+4   count (registers / payload bytes)
+5   address length: 1 if processor 0 and addr <= 0xFF, else 2
+6   address, big endian, 4 bytes
+10  payload (write data), count bytes
-2   16-bit checksum
```

The full 4-byte address is always present; byte 5 is only a statement about how
many of those bytes are meaningful. A one-byte register write is therefore 13
bytes, and a 48-byte firmware chunk in a command frame is 54.

### Commands (`afa.build_command`)

```
+0   length - 1
+1   command16 high
+2   command16 low
+3   sequence
+4   payload
-2   16-bit checksum
```

where `command16 = ((chip + processor) << 12) + command`. With `chip = 0`:
command 34 on the LINK processor (`0`) is `0x0022`; the same command on OFDM
(`8`) is `0x8022`.

### Checksum

Sum bytes from offset 1 up to `length - 2`, alternating high/low starting with
the high byte, then take the one's complement of the 16-bit sum:

```
total = 0
for i in 1 .. len-3:                       # offset 1 up to the checksum
    total += frame[i] << 8 if i is odd else frame[i]
checksum = (~total) & 0xFFFF
```

### Responses

A response is `[length-1][?][status][data…][checksum hi][checksum lo]`.
`afa.parse_response` requires all three of:

1. `len(response) == expected_data + 5`;
2. checksum over offsets 1..len-3 matches;
3. `status == 0`.

Byte 1 of the response is not interpreted, and the sequence number is **not**
compared with the request. A frame that fails any check is logged (with status
and the first 16 bytes) and treated as a failed operation; no retry is made at
this layer.

## 3. AFA command set

Only three commands are used by this driver:

| Id | Hex | Name | Sent to | Payload | Reply |
|---|---|---|---|---|---|
| 34 | `0x22` | firmware version | LINK, OFDM | `01` | 4 bytes, e.g. `05 05 00 00` |
| 35 | `0x23` | firmware start | LINK | — | — |
| 41 | `0x29` | firmware chunk | LINK | up to 48 bytes | — |

Register access is not in this table: it is command 0 and 1 of the *other* frame
family (section 2). There is no "start streaming" command — tune leaves the
demod streaming, and the host simply reads `0x84`.

Measured on 2026-10-19: firmware version read `05 05 00 00` on LINK and
`05 07 00 00` on OFDM. The driver only requires a non-zero reply; it does not
compare the version with the image (see section 4).

## 4. Firmware model

The image is **9,036 bytes**:

- 189 chunks, each 48 bytes except index 17 (39), 178 (47) and 188 (22) — the
  vendor's own chunk table, not an arbitrary split;
- it is sent only over the LINK processor as command 41;
- SHA-256 `451b09a40d072d3e7c0b805f3d180a8c8e10456a3768cce0cc27510c05c3575c`.

Upload sequence (`It9175Device.load_firmware`, only when the LINK firmware
version reads all zero):

```
write LINK 0x4BFB = 0x00
write LINK 0xCFFF = 0x00
write LINK 0xF103 = 0x07
189 × command 41 (chunks in order)
command 35 (start)
sleep 10 ms
```

`init()` then re-reads command 34 on LINK and fails if it is still zero. Only
after that does it write `LINK 0xF103 = 0x1A` and wake the OFDM processor
(`OFDM 0xEC4C = 0xA8`, 10 ms). The OFDM wake is probed with `OFDM 0x46`; if the
write or the probe fails, `diagnose_ofdm()` runs three recovery attempts
(`0xEC40 = 1`; power-saving `0xF84F 0→1`; GPIO bits `0xD8C8/9`, `0xD8BC/D`) and
re-queries the OFDM version. On the measured unit the very first write was
enough and none of the recovery paths ran.

Two honest limits, both visible in the code:

- the driver never verifies that the image *is* what is running, only that some
  non-zero version answers;
- a zero-filled buffer of the same length would pass the upload path — the
  simulator uses exactly that — because the bytes are never interpreted here.
  The SHA-256 check in `firmware.image()` is what keeps a wrong file off a real
  device.

## 5. Bring-up sequence

```
read LINK 0x1222            chip version        (1 byte)
read LINK 0x1223..24        chip id, LE         (0x9175 measured)
command 34 / LINK           fw version; upload if zero
write LINK 0xF103 = 0x1A
write OFDM 0xEC4C = 0xA8    wake OFDM; probe OFDM 0x46
command 34 / OFDM           fw version
Tuner.init()
```

`Tuner.init()`:

1. read `LINK 0xD800`; `clock = value & 0x0F`. Clock 0 selects the `*0`
   tables, anything else selects `*1`; values above 1 log a warning and still
   use the `*1` tables (the vendor's higher-clock path was never ported).
2. `INIT_A0` or `INIT_A1` — **141 script ops**.
3. `samba_init()` (below).
4. `INIT_B0` or `INIT_B1` — **111 script ops**.
5. three fixups: `M8:f993:fe:00`, `M8:f992:fe:01`, `W8:1e7:00`.

The script table is a mini-language (section 6). `INIT_A*` and `INIT_B*` write
the demodulator's register file; they are generated data, not logic, and live in
`it9175/tables.py` (`Tables.java` is the same data for Java).

`samba_init()` computes the frequency thresholds from what the tuner reports:

```
type = read OFDM 0xEC86        (0 on both the measured unit and the simulator)
ed03 = read OFDM 0xED03        divider: 3 in the simulator seed, 7 on the bench unit
ed23 = read OFDM 0xED23..24    clock, LE; poll up to 49 × 2 ms while zero
      type 0 → mulP/mulQ = 2000/3,   ed81 = 16
      type 1 → mulP/mulQ = 20480/18, ed81 = 6
      other  → mulP/mulQ = 640/1,    ed81 = 6
nv  = NV[ed03], NV = [48, 32, 24, 16, 12, 8, 6, 4, 2]
x5  = ed23 * mulP
x8  = x5 / mulQ
x7  = (x8 * 0xAAAAAAAAAAAAAAAB) >> 64        ≈ x8 * 2/3, truncating
thr[1] = x8 >> 5      thr[2] = x7 >> 4       thr[3] = x8 >> 4
thr[4] = x7 >> 3      thr[5] = x8 >> 3       thr[6] = x7 >> 2
thr[7] = x5 / (mulQ * nv)                    thr[8] = 950000 (default)
```

then reads `LINK 0x1222`, `LINK 0x1223..24`, sleeps 50 ms, writes `OFDM 0xED81`
(16 or 6), and if `OFDM 0x1DC == 1` also sets bits in `LINK 0xD8D0/D8D1`.

Simulator thresholds (seed `ec86=0`, `ed03=3`, `ed23=4642`; the values
`tests/test_tuner.py` asserts):
`[53000, 96708, 128944, 193416, 257888, 386833, 515777, 193416, 950000]` —
`thr[0]` is left at its default and unused. `thr[3]` and `thr[7]` both land on
193416 here because `thr[3] = x8 >> 4` and `thr[7] = x5 / (mulQ * nv)` with
`nv = 16`; they are equal only while those two roundings agree. That is the
vendor's arithmetic, not a mistake to "fix".

## 6. Script opcodes

`it9175/tables.py` stores each op as a short string; `Tuner.exec_op` interprets
it. `proc` is `0` (LINK) or `8` (OFDM); addresses and data are hex.

| Op | Form | Meaning |
|---|---|---|
| `M` | `M<proc>:<addr>:<and>:<or>` | read, write `(value & and) \| or` |
| `W` | `W<proc>:<addr>:<hex>` | write raw bytes |
| `I` | `I<proc>:<addr>:<hex>` | write **only if** the last `Q` was non-zero |
| `Q` | `Q<proc>:<addr>` | read; set the flag to `value != 0` |
| `P` | `P<proc>:<addr>` | poll until zero, 150 × 2 ms; timeout is logged but **not fatal** |
| `V` | `V<proc>` | query firmware version (command 34) |

`M` fails if the read fails; `W`/`I` fail if the write fails. A failed op stops
the script and fails the init/tune. `P` deliberately returns true on timeout
because the vendor ignores it.

## 7. Tune path

`Tuner.tune(freq_khz)`:

1. **`TUNE_PRE0`/`TUNE_PRE1`** (6 ops, by clock index):
   `M8:cfff:fc:00` (clear bits 0–1), write the 27-byte phase table at `OFDM
   0x11B`, write the 32-byte table at `OFDM 0x01`, `W8:40:00`, `W8:47:00`
   (clear lock/status), `M8:f999:fe:00`.
2. **Band code** to `OFDM 0x4B`:
   `freq <= 29999 → 0xFF`; `<= 300000 → 0`; `<= 1000000 → 1`;
   else `0xFF` if `freq - 1670000 > 10000`, otherwise `2`.
3. **Band row**, only if `OFDM 0x1C6 != 0`: choose `BANDS1` when
   `OFDM 0x1DC == 1`, else `BANDS0`; take the last row whose first field is
   `<= freq` (BANDS0 has 54 rows, BANDS1 105), then write
   `0xFB25=row[1]`, `0xFBB5=row[2]`, `0xFBB6=row[3]`, `0xFBB7=row[4]`,
   `0xFBB9=row[5]`, **`0xFBB9=row[6]` again**, `0xFBBA=row[7]`.
   The double write is in the vendor code; the second value is what sticks.
4. **`samba_set_freq`**:
   ```
   lna = lna_cap_sel(freq)
   lpf = lpf_bw(6000 kHz) = 2
   b5a = (OFDM 0xEC4C & 231) | (8 if freq > 311999)
   iq  = cal_freq_iqik(freq, OFDM 0xED81)
   lo  = lo_freq(freq)
   write OFDM 0x160  = lna
   write OFDM 0xEC56 = lpf
   write OFDM 0xEC4C = b5a
   write OFDM 0xEC4D = iq & 0xFF        # IQ compensation, low byte
   write OFDM 0xEC4E = iq >> 8          # IQ compensation, high byte
   write OFDM 0x015E = lo & 0xFF        # LO word, low byte
   write OFDM 0x015F = lo >> 8          # LO word, high byte
   if OFDM 0x1DC == 1:
       write LINK 0xD8CF = (read & 254) | (1 if freq > 176142)
   half = freq >> 1
   write OFDM 0x1E3  = lna_cap_sel(half)
   write OFDM 0x1E1  = lo_freq(half) & 0xFF
   write OFDM 0x1E2  = lo_freq(half) >> 8
   ```
5. `write OFDM 0x00 = 0`.

### Tuning maths

```
nc  = get_nc(freq)
      nc = 0   if freq <= thr[1]
      nc = k   if freq <= thr[k+1], for k = 1..6
      nc = 7   if freq <= thr[8]
      nc = 8   above thr[8]
nv  = NV[nc]
fcw = round(mulQ * freq * nv / mulP)        round half up
lo  = ((nc & 7) << 13) + fcw
```

IQ compensation (`cal_freq_iqik`, `p = OFDM 0xED81`):

```
type 0:  p <= 31 → fcw + ((9 * nv * p) >> 5)
         p >  31 → fcw - ((9 * nv * (64 - p)) >> 5)
type 1:  p <= 31 → fcw + ((p * nv) >> 1)
         p >  31 → fcw - (((64 - p) * nv) >> 1)
other:   always  → fcw - (((64 - p) * nv) >> 1)
```

Note the last branch: the vendor's `p <= 31` test also requires `type == 1`, so
a type-2 unit always subtracts, even on the low side. The port keeps that.

then packed as `((nc & 7) << 13) + x`.

Auxiliary tables:

```
lna_cap_sel(freq):  <=440000→0  <=484000→1  <=533000→2  <=587000→3
                    <=645000→4  <=710000→5  else 6 if freq-710001 <= 71999 else 7
lpf_bw(khz):        5000→0 5500→1 6000→2 6500→3 7000→4 7500→5 8000→6 8500→7
```

Golden values (also asserted by `tests/test_tuner.py`, cross-checked against
the Java reference with `tools/java_math_check.py`):

| freq kHz | nc | nv | fcw | lo | iq(16) |
|---|---|---|---|---|---|
| 473143 | 5 | 8 | 5678 | 46638 | 46674 |
| 497143 | 5 | 8 | 5966 | 46926 | 46962 |
| 599143 | 7 | 4 | 3595 | 60939 | 60957 |
| 671143 | 7 | 4 | 4027 | 61371 | 61389 |
| 695143 | 7 | 4 | 4171 | 61515 | 61533 |

Measured hardware words at 599.143 MHz on 2026-10-19 were `lo=0xD510`
(54,544) and `iq=0xD52B` (54,571) — the hardware's thresholds differ from the
simulator's, so compare those two numbers with a run's own threshold line, not
with this table.

## 8. Lock and status

`Tuner.wait_lock(quick=False)`:

1. poll `OFDM 0x47`: 40 polls × 25 ms per attempt, two attempts (quick: one
   attempt of 60 polls). State `1` goes on; state `2` skips the TPS/MPEG2
   checks and, on the first attempt, clears `0x47` and `LINK 0x00` before the
   retry. A second attempt in state `2` gives up.
2. poll `OFDM 0xF5A9` bit 0 up to 50 × 25 ms (TPS).
3. poll `OFDM 0xF9F1`, `0xF9F2`, `0xF9F3` bit 0 up to 40 × 25 ms (MPEG2);
   any of the three set is enough.

`status()` reads:

| field | register | scaling |
|---|---|---|
| strength | `OFDM 0x13E` | clamped to 100 (%) |
| quality | `OFDM 0x49` | clamped to 100 (%) |
| dBm | `OFDM 0x13F` | minus 100 |
| SNR | `OFDM 0x1C9` | raw dB |
| BER errors | `OFDM 0x32+2..4` | 24-bit LE |
| BER window | `OFDM 0x32+5..6` | 16-bit LE |
| BER | computed | `errors / (window * 204 * 8)` |

`locked` requires `0xF5A9` bit 0 **and** one of `0xF9F1..F9F3` bit 0.

## 9. The simulator, and what it is not

`SimBackend` (in `it9175/device.py`) implements the same `write`/`read`/
`read_ts` interface. It seeds the registers the init path reads, records writes
in a dict, reports firmware version `05 05 00 00` once command 35 has been seen,
returns `1` from `OFDM 0x4C` exactly once after that register is written (then
`0`) to mimic the firmware consuming it, returns `1` for `OFDM 0x47`, and
synthesises aligned TS packets.

It exists so the framing, command order, tables, tuning maths and TS alignment
can be tested without hardware. It cannot show what a register *becomes*: every
value it returns was written into it (or seeded), `0x47` does not model lock at
all, and no timing, RF, firmware execution or USB failure is simulated. A sim
pass is evidence about this code's ordering and arithmetic, never about silicon.
`docs/verification.md` keeps the two kinds of evidence separate.

## 10. Open questions

- Response byte 1 is unread; its meaning is unknown.
- Sequence numbers are not checked on the way back, so a delayed response from
  the previous command cannot be told apart from the current one.
- Tuner type 2 (`mulP/mulQ = 640/1`) is implemented from the vendor branch but
  no such unit has been seen.
- The higher-clock `*1` tables are used whenever `LINK 0xD800 & 0x0F != 0`;
  values above 1 warn and fall back rather than following the vendor's
  unported path.
- Off-air behaviour, macOS, and Linux are untested (see the README's "Not yet
  proven" list); none of them is a protocol question.
