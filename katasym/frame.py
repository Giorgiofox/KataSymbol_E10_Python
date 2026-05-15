"""Wire-frame builders for the E10 protocol.

Command frame (verified against BasePrint.sendCmd(byte, int, byte[]) and
sendCmdRandom — note the length field is `frame_size - 4`, NOT `len(payload) + 8`
as an earlier draft assumed):

    [0]   0x7E
    [1]   0x5A
    [2-3] LE16 length = frame_size - 4 (= len(payload) + 6 with our offset)
    [4]   0x10 (HEADER_BYTE_4)
    [5]   0x01 cmd / 0x02 data
    [6]   0xAA (HEADER_BYTE_6)
    [7]   opcode
    [8-9] LE16 checksum = sum(payload) mod 2**16
    [10+] payload

The int-param overload `BasePrint.sendCmd(byte b, int i, byte[])` produces a
**16-byte** frame with the payload exactly:

    [10] 0x00
    [11] 0x01
    [12] param_lo
    [13] param_hi
    [14] 0x00
    [15] 0x00

so the checksum is computed over 6 payload bytes (the two trailing zeros are
*essential* — the printer firmware will not respond to the 14-byte short form).

DMA chunk:
    [0]   0xAA
    [1]   0xBB
    [2-3] LE16 checksum = sum(bytes[4..505])
    [4]   chunk index
    [5]   total chunks
    [6..505] 500 bytes of compressed data (zero-padded)
"""
from __future__ import annotations

from .constants import (
    MAGIC_0, MAGIC_1, HEADER_BYTE_4, HEADER_BYTE_6,
    FRAME_TYPE_CMD,
    DMA_MAGIC_0, DMA_MAGIC_1, DMA_CHUNK_SIZE, DMA_DATA_PER_CHUNK,
    DMA_ENVELOPE_SIZE, DMA_ENVELOPE_HEADER, DMA_BLE_SUBCHUNK,
)


def checksum_sum(data: bytes | bytearray) -> int:
    """Unsigned-byte sum mod 2**16 — used everywhere in the protocol."""
    return sum(b & 0xFF for b in data) & 0xFFFF


def build_command_frame(
    opcode: int,
    payload: bytes | bytearray = b"",
    frame_type: int = FRAME_TYPE_CMD,
) -> bytes:
    """Build a fully-framed command (header + opcode + checksum + payload).

    Mirrors BasePrint.sendCmdRandom (BasePrint.java:762-769): length field at [2-3] is
    `frame_size - 4` = `len(payload) + 6` for our offset, checksum at [8-9] covers
    `payload` bytes only.
    """
    length_field = len(payload) + 6
    csum = checksum_sum(payload)

    out = bytearray(10 + len(payload))
    out[0] = MAGIC_0
    out[1] = MAGIC_1
    out[2] = length_field & 0xFF
    out[3] = (length_field >> 8) & 0xFF
    out[4] = HEADER_BYTE_4
    out[5] = frame_type & 0xFF
    out[6] = HEADER_BYTE_6
    out[7] = opcode & 0xFF
    out[8] = csum & 0xFF
    out[9] = (csum >> 8) & 0xFF
    out[10:] = payload
    return bytes(out)


def build_command_frame_int_param(opcode: int, param: int = 0) -> bytes:
    """Single-int parameter variant — matches BasePrint.sendCmd(byte b, int i, byte[]).

    Builds the canonical **16-byte** fixed-payload frame:
        payload = [0x00, 0x01, param_lo, param_hi, 0x00, 0x00]
    Length field = 12 (frame_size - 4). The two trailing zeros ARE required —
    short 14-byte versions are silently rejected by the firmware.
    """
    payload = bytes([
        0x00, 0x01,
        param & 0xFF, (param >> 8) & 0xFF,
        0x00, 0x00,
    ])
    return build_command_frame(opcode, payload, FRAME_TYPE_CMD)


def build_dma_chunk(chunk_idx: int, total_chunks: int, data: bytes | bytearray) -> bytes:
    """Build one 506-byte DMA chunk carrying up to 500 bytes of compressed raster."""
    if len(data) > DMA_DATA_PER_CHUNK:
        raise ValueError(f"chunk data too large: {len(data)} > {DMA_DATA_PER_CHUNK}")
    out = bytearray(DMA_CHUNK_SIZE)
    out[0] = DMA_MAGIC_0
    out[1] = DMA_MAGIC_1
    # checksum bytes (2,3) computed last
    out[4] = chunk_idx & 0xFF
    out[5] = total_chunks & 0xFF
    out[6:6 + len(data)] = data
    csum = checksum_sum(out[4:DMA_CHUNK_SIZE])
    out[2] = csum & 0xFF
    out[3] = (csum >> 8) & 0xFF
    return bytes(out)


def split_into_dma_chunks(compressed: bytes) -> list[bytes]:
    """Slice an LZMA-compressed pre-LZMA buffer into DMA chunks."""
    total = (len(compressed) + DMA_DATA_PER_CHUNK - 1) // DMA_DATA_PER_CHUNK
    chunks: list[bytes] = []
    for i in range(total):
        slc = compressed[i * DMA_DATA_PER_CHUNK : (i + 1) * DMA_DATA_PER_CHUNK]
        chunks.append(build_dma_chunk(i, total, slc))
    return chunks


def wrap_dma_envelope(chunk: bytes) -> bytes:
    """Wrap a 506-byte DMA chunk in the 512-byte outer envelope for E-class devices.

    Matches BasePrint.transferSplitData() (BasePrint.java:857-865) — pre-pends the
    6-byte header `7E 5A FC 01 10 02` then the chunk; pads to 512 bytes.
    """
    if len(chunk) != DMA_CHUNK_SIZE:
        raise ValueError(f"DMA chunk must be {DMA_CHUNK_SIZE}B, got {len(chunk)}")
    out = bytearray(DMA_ENVELOPE_SIZE)
    out[0:len(DMA_ENVELOPE_HEADER)] = DMA_ENVELOPE_HEADER
    out[len(DMA_ENVELOPE_HEADER):len(DMA_ENVELOPE_HEADER) + len(chunk)] = chunk
    return bytes(out)


def split_envelope_for_ble(envelope: bytes) -> list[bytes]:
    """Split a 512-byte DMA envelope into 4 × 128-byte BLE writes."""
    if len(envelope) != DMA_ENVELOPE_SIZE:
        raise ValueError(f"envelope must be {DMA_ENVELOPE_SIZE}B, got {len(envelope)}")
    return [
        envelope[i * DMA_BLE_SUBCHUNK:(i + 1) * DMA_BLE_SUBCHUNK]
        for i in range(DMA_ENVELOPE_SIZE // DMA_BLE_SUBCHUNK)
    ]


# --- Response parsing helpers ---

def parse_frame_header(buf: bytes) -> dict | None:
    """Return {length, frame_type, opcode, checksum, payload} or None if no header match."""
    if len(buf) < 10 or buf[0] != MAGIC_0 or buf[1] != MAGIC_1:
        return None
    length_field = buf[2] | (buf[3] << 8)
    return {
        "length_field": length_field,
        "byte4": buf[4],
        "frame_type": buf[5],
        "byte6": buf[6],
        "opcode": buf[7],
        "checksum": buf[8] | (buf[9] << 8),
        "payload": bytes(buf[10:]),
    }
