"""Bitmap → bitplane raster, matching ImgConverter.GetAllBytes from the app.

Layout produced (verified against ImgConverter.java:63-87):
- One byte per 8 vertical dots in a given column.
- LSB (bit 0) = topmost dot (y=0); MSB (bit 7) = 8th dot (y=7).
- Columns stored sequentially: all bytes of column 0, then column 1, ...
- For E10: height = 96 dots → 12 bytes per column.

Threshold default 125. No dithering. Alpha channel ignored.
"""
from __future__ import annotations

from PIL import Image

from .constants import DEFAULT_THRESHOLD


def pack_bitmap(img: Image.Image, threshold: int = DEFAULT_THRESHOLD) -> bytes:
    """Pack a PIL image into the printer's column-major 1bpp byte stream.

    Pixels darker than `threshold` (per 0.30 R + 0.59 G + 0.11 B luminance) become "on" dots.
    """
    rgb = img.convert("RGB")
    width, height = rgb.size
    bytes_per_column = (height + 7) // 8
    out = bytearray(width * bytes_per_column)

    px = rgb.load()
    for x in range(width):
        col_base = x * bytes_per_column
        for y in range(height):
            r, g, b = px[x, y]
            gray = int(0.30 * r + 0.59 * g + 0.11 * b)
            if gray < threshold:
                out[col_base + (y >> 3)] |= 1 << (y & 7)
    return bytes(out)


def fit_to_head(img: Image.Image, head_dots: int) -> Image.Image:
    """Pad/crop the image so its height matches the printer head width in dots.

    The E10 head is 96 dots wide. Many input images will not be 96 px tall;
    this helper centers them on the head height (white background).
    """
    w, h = img.size
    if h == head_dots:
        return img
    out = Image.new("RGB", (w, head_dots), (255, 255, 255))
    out.paste(img, (0, max(0, (head_dots - h) // 2)))
    return out
