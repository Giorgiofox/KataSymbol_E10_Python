"""Pre-LZMA page frame buffer + PAGE_REG_BITS encoding.

Pre-LZMA frame buffer (T15Print.initLZMAData, T15Print.java:497-532):

    [0-1]   LE16 checksum  (over bytes [2..end])
    [2-3]   PAGE_REG_BITS  (2 bytes)
    [4-5]   LE16 column count = label width in dots
    [6]     mPerLineByte = 12 for E10
    [7]     0x00
    [8]     0x01
    [9]     0x00
    [10]    0x01
    [11]    0x00
    [12]    iGetNoZeroIndex  (raster trim offset; left-most non-zero column from raster)
    [13]    0x00
    [14+]   raster bytes (column_count * mPerLineByte)

PAGE_REG_BITS (PAGE_REG_BITS.java:17-39):

    byte 0:
        bit 1: PageSt
        bit 2: PageEnd
        bit 3: PrtEnd
        bits 4-6: Cut (3 bits)
        bit 7: Savepaper
    byte 1:
        bits 0-1: FirstCut
        bits 2-3: Nodu
        bits 4-7: Mat (shifted by matShift; T15Print passes 4)
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import DEFAULT_MAT_SHIFT, E10_BYTES_PER_COLUMN
from .frame import checksum_sum


@dataclass
class PageRegBits:
    page_st: int = 1
    page_end: int = 1
    prt_end: int = 1
    cut: int = 0
    savepaper: int = 0
    first_cut: int = 0
    nodu: int = 0
    mat: int = 1

    def to_bytes(self, mat_shift: int = DEFAULT_MAT_SHIFT) -> bytes:
        b0 = 0
        b0 |= (self.page_st & 1) << 1
        b0 |= (self.page_end & 1) << 2
        b0 |= (self.prt_end & 1) << 3
        b0 |= (self.cut & 0b111) << 4
        b0 |= (self.savepaper & 1) << 7

        b1 = 0
        b1 |= (self.first_cut & 0b11)
        b1 |= (self.nodu & 0b11) << 2
        # Mat occupies bits [mat_shift..7]. For T15/E10 mat_shift=4.
        b1 |= (self.mat & (0xFF >> mat_shift)) << mat_shift
        b1 &= 0xFF

        return bytes([b0, b1])


def build_pre_lzma_buffer(
    raster: bytes,
    column_count: int,
    page_reg: PageRegBits,
    per_line_byte: int = E10_BYTES_PER_COLUMN,
    no_zero_index: int = 0,
    mat_shift: int = DEFAULT_MAT_SHIFT,
) -> bytes:
    """Assemble the pre-LZMA frame buffer for one print page.

    `column_count` must equal len(raster) / per_line_byte.
    """
    expected = column_count * per_line_byte
    if len(raster) != expected:
        raise ValueError(
            f"raster length {len(raster)} != column_count*per_line_byte={expected}"
        )

    out = bytearray(14 + len(raster))
    # [2-3] PAGE_REG_BITS
    out[2:4] = page_reg.to_bytes(mat_shift)
    # [4-5] LE16 column count
    out[4] = column_count & 0xFF
    out[5] = (column_count >> 8) & 0xFF
    # [6] bytes per line
    out[6] = per_line_byte & 0xFF
    # [7..13] fixed/derived bytes (verified against T15Print.java:510-516)
    out[7]  = 0x00
    out[8]  = 0x01
    out[9]  = 0x00
    out[10] = 0x01
    out[11] = 0x00
    out[12] = no_zero_index & 0xFF
    out[13] = 0x00
    # [14+] raster
    out[14:] = raster

    # [0-1] LE16 checksum (T15Print.java:517-529): header bytes [2..13]
    # + bytes sampled at every 256-th position (255, 511, 767, ...) up to
    # floor(total_len / 256). The full-buffer sum we used previously was wrong.
    total_len = column_count * per_line_byte + 14
    csum = 0
    for i in range(2, 14):
        csum += out[i]
    for i in range(1, total_len // 256 + 1):
        csum += out[i * 256 - 1]
    csum &= 0xFFFF
    out[0] = csum & 0xFF
    out[1] = (csum >> 8) & 0xFF
    return bytes(out)
