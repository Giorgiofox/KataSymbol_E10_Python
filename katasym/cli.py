"""Command-line entrypoint:

    python -m katasym scan
    python -m katasym status --address <BLE addr>
    python -m katasym print  --address <BLE addr> --image label.png [--concentration 4] [--copies 1]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .ble import E10Connection, discover
from .constants import E10_HEAD_DOTS
from .protocol import E10Printer


def render_text_image(text: str, font_size: int = 56, padding: int = 20,
                      box: bool = False, box_width: int = 3,
                      box_inset: int = 4) -> Image.Image:
    """Render `text` into a 96-dot-tall white PNG with black glyphs.

    If `box` is set, draw a rectangular border inset by `box_inset` px from the
    image edges with `box_width` px stroke.
    """
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except OSError:
            font = ImageFont.load_default()
    dummy = Image.new("L", (1, 1), 255)
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    img = Image.new("RGB", (text_w + 2 * padding, E10_HEAD_DOTS), (255, 255, 255))
    y = (E10_HEAD_DOTS - text_h) // 2 - bbox[1]
    draw = ImageDraw.Draw(img)
    draw.text((padding, y), text, fill=(0, 0, 0), font=font)
    if box:
        w, h = img.size
        draw.rectangle(
            (box_inset, box_inset, w - 1 - box_inset, h - 1 - box_inset),
            outline=(0, 0, 0), width=box_width,
        )
    return img


log = logging.getLogger("katasym.cli")


async def cmd_scan(timeout: float, all_devices: bool) -> int:
    devs = await discover(timeout=timeout, only_e10=not all_devices)
    if not devs:
        print("no devices found")
        return 1
    for d in devs:
        rssi = f"{d.rssi:>4} dBm" if d.rssi is not None else "  ?? dBm"
        print(f"  {d.address}  {rssi}  {d.display:<14}  raw='{d.name}'")
    return 0


async def _resolve_address(address: str | None) -> str | None:
    """Return `address` if given, else scan and return the first E10 found."""
    if address:
        return address
    log.info("no --address given; scanning for an E10 ...")
    devs = await discover(timeout=6.0, only_e10=True)
    if not devs:
        print("error: no E10 found on scan; pass --address or check the printer is on")
        return None
    dev = devs[0]
    log.info("auto-picked %s (%s, rssi=%s dBm)", dev.address, dev.display, dev.rssi)
    return dev.address


async def cmd_status(address: str, with_response: bool, opcode: int) -> int:
    async with E10Connection(address) as conn:
        printer = E10Printer(conn)
        status = await printer.inquiry_status(
            timeout=2.0, with_response=with_response, opcode=opcode,
        )
        if status is None:
            print("no status reply")
            return 2
        msta, fsta = status
        print("MSTA:", msta)
        print("FSTA:", fsta)
        return 0


async def cmd_diag(address: str) -> int:
    """Dump services + chars, subscribe to every NOTIFY char, then sweep writes."""
    from bleak import BleakClient
    from .frame import build_command_frame_int_param, parse_frame_header
    from .constants import CMD_INQUIRY_STA, CMD_READ_FWVER, CMD_RD_DEV_NAME

    client = BleakClient(address)
    await client.connect()
    try:
        print(f"connected (mtu={client.mtu_size})")
        print("\n=== services / characteristics ===")
        notify_chars: list[str] = []
        write_chars: list[tuple[str, bool, bool]] = []  # (uuid, supports_write, supports_no_resp)
        for svc in client.services:
            print(f"SERVICE {svc.uuid}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"   CHAR {ch.uuid}  props=[{props}]  handle={ch.handle}")
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notify_chars.append(str(ch.uuid))
                if "write" in ch.properties or "write-without-response" in ch.properties:
                    write_chars.append((
                        str(ch.uuid),
                        "write" in ch.properties,
                        "write-without-response" in ch.properties,
                    ))

        # subscribe to every NOTIFY char and tag the source on each packet
        from collections import deque
        events: deque[tuple[str, bytes]] = deque()

        def make_cb(uuid: str):
            def cb(_, data: bytearray) -> None:
                events.append((uuid, bytes(data)))
            return cb

        for nu in notify_chars:
            try:
                await client.start_notify(nu, make_cb(nu))
                print(f"subscribed to NOTIFY {nu}")
            except Exception as e:
                print(f"could NOT subscribe to {nu}: {e!r}")

        # give the printer 2s to settle after connect (mirrors the 1500ms in BLEUtils)
        print("\nwaiting 2s post-connect ...")
        await asyncio.sleep(2.0)
        if events:
            print("spontaneous notifies during settle:")
            while events:
                u, d = events.popleft()
                print(f"   {u} <- {d.hex()}")

        async def probe(label: str, opcode: int, write_uuid: str, with_resp: bool):
            print(f"\n--- {label}: opcode=0x{opcode:02x} via WRITE {write_uuid} resp={with_resp} ---")
            events.clear()
            frame = build_command_frame_int_param(opcode, 0)
            print(f"TX ({len(frame)}B): {frame.hex()}")
            try:
                await client.write_gatt_char(write_uuid, frame, response=with_resp)
            except Exception as e:
                print(f"write failed: {e!r}")
                return
            loop = asyncio.get_event_loop()
            deadline = loop.time() + 1.5
            while loop.time() < deadline:
                if events:
                    while events:
                        u, d = events.popleft()
                        print(f"RX [{u}] ({len(d)}B): {d.hex()}")
                await asyncio.sleep(0.05)

        # for each WRITE-capable char, send INQUIRY_STA in both write modes
        for wu, can_write, can_nrw in write_chars:
            if can_nrw:
                await probe(f"INQUIRY_STA no-resp on {wu}", CMD_INQUIRY_STA, wu, False)
                await asyncio.sleep(0.2)
            if can_write:
                await probe(f"INQUIRY_STA with-resp on {wu}", CMD_INQUIRY_STA, wu, True)
                await asyncio.sleep(0.2)

        # also try alt opcode 0x13 and READ_FWVER on every write-no-resp char
        for wu, _, can_nrw in write_chars:
            if can_nrw:
                await probe(f"opcode 0x13 on {wu}", 0x13, wu, False)
                await asyncio.sleep(0.2)
                await probe(f"READ_FWVER on {wu}", CMD_READ_FWVER, wu, False)
                await asyncio.sleep(0.2)

        for nu in notify_chars:
            try:
                await client.stop_notify(nu)
            except Exception:
                pass
    finally:
        await client.disconnect()
    return 0


async def cmd_print(address: str, image: Path | None, text: str | None,
                    font_size: int, concentration: int, copies: int,
                    threshold: int, box: bool) -> int:
    if text is not None:
        img = render_text_image(text, font_size=font_size, box=box)
    elif image is not None:
        img = Image.open(image)
    else:
        print("error: pass --image or --text")
        return 2
    async with E10Connection(address) as conn:
        printer = E10Printer(conn)
        await printer.print_image(
            img,
            concentration=concentration,
            copies=copies,
            threshold=threshold,
        )
    print("done")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="katasym")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="discover E10 printers")
    p_scan.add_argument("--timeout", type=float, default=8.0)
    p_scan.add_argument("--all", action="store_true",
                        help="list every BLE device, not only matched E10 serials")

    p_status = sub.add_parser("status", help="query MSTA/FSTA on a printer")
    p_status.add_argument("--address", default=None,
                          help="BLE address (CoreBluetooth UUID on macOS); auto-scan if omitted")
    p_status.add_argument("--with-response", action="store_true",
                          help="use BLE WRITE (with response) instead of WRITE_NO_RESPONSE")
    p_status.add_argument("--opcode", type=lambda s: int(s, 0), default=0x11,
                          help="override INQUIRY opcode (default 0x11; some firmwares use 0x13)")

    p_diag = sub.add_parser("diag",
                            help="dump GATT + try multiple inquiry variants (debug)")
    p_diag.add_argument("--address", default=None,
                        help="BLE address; auto-scan if omitted")

    p_print = sub.add_parser("print", help="print a single image or text string")
    p_print.add_argument("--address", default=None,
                         help="BLE address; auto-scan if omitted")
    src = p_print.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", type=Path, help="path to a PNG/JPEG")
    src.add_argument("--text", help="render the given text and print it")
    p_print.add_argument("--font-size", type=int, default=56,
                         help="font size when --text is used (default 56)")
    p_print.add_argument("--concentration", type=int, default=4)
    p_print.add_argument("--copies", type=int, default=1)
    p_print.add_argument("--threshold", type=int, default=125)
    p_print.add_argument("--box", action="store_true",
                         help="draw a rectangular border around the rendered text")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname).1s %(name)s | %(message)s")

    if args.cmd == "scan":
        return asyncio.run(cmd_scan(args.timeout, args.all))

    async def _run() -> int:
        addr = await _resolve_address(args.address)
        if addr is None:
            return 3
        if args.cmd == "status":
            return await cmd_status(addr, args.with_response, args.opcode)
        if args.cmd == "diag":
            return await cmd_diag(addr)
        if args.cmd == "print":
            return await cmd_print(
                addr, args.image, args.text, args.font_size,
                args.concentration, args.copies, args.threshold, args.box)
        return 1

    if args.cmd in ("status", "diag", "print"):
        return asyncio.run(_run())
    return 1


if __name__ == "__main__":
    sys.exit(main())
