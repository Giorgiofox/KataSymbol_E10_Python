# KataSymbol E10 — Python client

Standalone Python client to drive the **Katasymbol E10** BLE thermal label
printer (`printerType=15`, T15 firmware family) from a Mac or Linux box,
without the official Android app.

> Unofficial project. Not affiliated with Supvan / Katasymbol.

## Features

- BLE discovery filtered against the known E10 serial allowlist (75 entries)
- `MSTA` / `FSTA` status register read (busy, cover open, label end, …)
- PNG / JPEG image printing
- Text rendering and printing in a single command
- Optional rectangular border around rendered text (`--box`)
- Concentration 1–7 and multi-copy
- Full raster → pre-LZMA buffer → LZMA-Alone → DMA pipeline (506-byte
  chunks wrapped in a 512-byte envelope, then split into 4×128-byte BLE
  writes with 50 ms inter-write delay — matches what the Android app sends)

## Hardware supported

- **Katasymbol E10** (direct thermal, BLE only)
- 96-dot head (203 dpi), 12 bytes per column
- Concentration 1–7, copies 1–100
- T15 / Series 2 firmware

The 75 known serials are listed in `katasym/constants.py`. If your printer's
serial is outside that allowlist, `katasym scan` will not show it — pass
`--all` to see every BLE device and use the address manually.

## Install

### With [uv](https://github.com/astral-sh/uv) (recommended)

```bash
git clone https://github.com/Giorgiofox/KataSymbol_E10_Python.git
cd KataSymbol_E10_Python
uv sync
```

### With pip

```bash
git clone https://github.com/Giorgiofox/KataSymbol_E10_Python.git
cd KataSymbol_E10_Python
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Runtime dependencies: `bleak >= 0.22`, `pillow >= 10`. Python ≥ 3.10.

## Usage

### Discovery

```bash
uv run katasym scan
```

Lists every reachable E10 with its RSSI. Sample output:

```
  <BLE-UUID-or-MAC>   -46 dBm  E10 T00XX       raw='T00XX<serial-tail>'
```

On macOS the address is a CoreBluetooth UUID, not a real MAC. On Linux it
is a standard MAC.

### Printer status

```bash
uv run katasym status
```

`--address` is optional on every subcommand. When omitted, a quick scan runs
and the first matching E10 is used. To target a specific printer:

```bash
uv run katasym status --address <BLE-UUID-or-MAC>
```

### Print text

```bash
uv run katasym print --text "Hello E10"
uv run katasym print --text "Hello E10" --concentration 7 --copies 2
uv run katasym print --text "Hello E10" --box
```

Relevant flags:

| Flag | Default | Meaning |
|---|---|---|
| `--text "..."` | — | text to render (mutually exclusive with `--image`) |
| `--image FILE` | — | PNG / JPEG file path |
| `--font-size N` | 56 | font size used with `--text` |
| `--concentration N` | 4 | thermal head density 1–7 (higher = darker) |
| `--copies N` | 1 | number of copies |
| `--threshold N` | 125 | bitmap binarization threshold (0–255) |
| `--box` | off | draw a rectangular border around the rendered text |
| `--address ADDR` | auto | BLE address; auto-scan if omitted |

### Print an image

```bash
uv run katasym print --image label.png --concentration 6
```

The input image is centered on a 96-dot-tall canvas (= head width); the
canvas width determines the printed label length. For predictable output,
supply a PNG that is already 96 px tall.

### BLE diagnostics

```bash
uv run katasym diag
```

Dumps every service / characteristic in the GATT tree, subscribes to all
notify characteristics, and probes inquiry with several opcodes (`0x11`,
`0x13`, `0xC5`) on every writable characteristic. Useful if the printer
stops responding — helps locate firmware-side changes.

## Programmatic example

```python
import asyncio
from PIL import Image
from katasym.ble import E10Connection, discover
from katasym.protocol import E10Printer

async def main():
    devs = await discover(timeout=6.0)
    addr = devs[0].address
    img = Image.open("label.png")
    async with E10Connection(addr) as conn:
        printer = E10Printer(conn)
        await printer.print_image(img, concentration=6, copies=1)

asyncio.run(main())
```

See `examples/print_text.py` for a complete script.

## Client layout

```
katasym/
  constants.py   Opcodes, GATT UUIDs, E10 parameters, serial allowlist
  frame.py       Command frame builder (16 B) + DMA chunk (506 B)
                 + outer envelope (512 B) + 4×128 BLE split
  raster.py      PIL bitmap → 1bpp column-major stream (LSB = top dot)
  page.py        Pre-LZMA buffer header + PAGE_REG_BITS encoding
  compress.py    LZMA-Alone wrapper (dict 8192, lc=3, pb=2, …)
  status.py      MSTA / FSTA decoder
  ble.py         bleak transport (scan, connect, write, notify queue)
  protocol.py    End-to-end print state machine
  cli.py         argparse CLI (scan / status / diag / print)
```

## Protocol notes

- **GATT service**: `0000e0ff-3c17-d293-8e48-14fe2e4da212`
- **Write char**: `0000ffe9-…` (write + write-without-response)
- **Notify char**: `0000ffe1-…` (notify + write)
- **MTU**: 240 (negotiated; macOS may cap lower)
- **Command frame**: fixed 16 bytes, `7E 5A LL 00 10 01 AA OP CS_LE16 [6-byte param]`
- **Density**: opcode `0xC9`, wire value = `int(((conc-1)/10 + 0.8) * 100)` →
  80/90/100/110/120/130/140 for concentration 1–7
- **Start print**: opcode `0x13`
- **Bulk transfer**: opcode `0x5C` with `[page_size LE16][num_chunks LE16]`,
  followed by N DMA chunks of 506 bytes each (`AA BB cs idx tot` + 500 LZMA
  bytes)
- **BLE chunk envelope**: each 506-byte DMA chunk is wrapped in a 512-byte
  `7E 5A FC 01 10 02 + chunk` envelope and split into 4×128-byte BLE writes
  with a 50 ms delay between writes
- **Buf full**: opcode `0x10` after the last chunk

The LZMA stream is the classic `.lzma` (LZMA-Alone) container: 5-byte
properties header + 8-byte LE64 size + payload. Parameters: `dict_size=8192`,
`lc=3`, `lp=0`, `pb=2`, `nice_len=128`.

## Known limits

- Tested on Series 2 firmware. Other sub-models may need tuning of
  `dict_size`, `mat_shift`, or opcodes.
- macOS addresses are CoreBluetooth UUIDs — they rotate over time; just
  re-scan when one stops resolving.
- Very wide labels (> 332 columns) follow a multi-frame path in the
  original app; this client implements the single-frame path only and has
  not been validated for the wider case.
- Optional auth challenges (`CMD_READ_RANDOM = 0xD5`,
  `CMD_VERIFY_RANDOM = 0xD6`) are not implemented — not required on the
  test unit, but present in other firmware revisions.

## License

MIT — see [`LICENSE`](LICENSE).

This client is intended for interoperability with hardware bought legally.
No firmware, app binaries, or proprietary assets are included.
