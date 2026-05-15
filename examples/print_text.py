# /// script
# requires-python = ">=3.10"
# dependencies = ["bleak>=0.22", "pillow>=10.0", "katasym"]
# ///
"""Example: render a short text into a 96-dot-tall image and print it on an E10.

Usage:
    # inside the project venv (after `uv sync` or `pip install -e .`):
    uv run examples/print_text.py --address <BLE addr> "Hello E10"

    # the `katasym` CLI does the same:
    uv run katasym print --address <addr> --text "Hello E10"
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from PIL import Image, ImageDraw, ImageFont

from katasym.ble import E10Connection
from katasym.protocol import E10Printer


HEAD_DOTS = 96


def render_text(text: str, font_size: int = 56) -> Image.Image:
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    dummy = Image.new("L", (1, 1), 255)
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    img = Image.new("RGB", (text_w + 40, HEAD_DOTS), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = (HEAD_DOTS - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((20, y), text, fill=(0, 0, 0), font=font)
    return img


async def main(address: str, text: str, copies: int) -> int:
    img = render_text(text)
    async with E10Connection(address) as conn:
        printer = E10Printer(conn)
        await printer.print_image(img, copies=copies)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--address", required=True)
    p.add_argument("--copies", type=int, default=1)
    p.add_argument("text")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.address, args.text, args.copies)))
