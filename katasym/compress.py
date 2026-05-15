"""LZMA-Alone (.lzma) encoder matching LzmaUtils from the app.

Java side (LzmaUtils.java:21):
    SetCoderProperties(
        propIDs=[1136, 1024, 1168, 1089, 1090, 1105, 1104, 1088],
        values =[2,    8192, 0,    3,    0,    1,    128,  2]
    )

Decoding the 7-Zip Java SDK property IDs (from LZMA SDK source):
    1024 = kDictionarySize    -> 8192
    1088 = kPosStateBits      -> 2
    1089 = kLitContextBits    -> 3
    1090 = kLitPosBits        -> 0
    1104 = kNumFastBytes      -> 128
    1105 = kMatchFinder       -> 1   (1 == BT2 in 7-Zip Java SDK; BT4 is value 2)
    1136 = kEndMarker         -> 2   (?)
    1168 = (vendor extension) -> 0

Output stream layout (LzmaUtils.java:22-27):
    [0..4]  5-byte ".lzma" properties header (lc/lp/pb + dict size)
    [5..12] LE64 uncompressed size (8 bytes)
    [13+]   compressed payload

This matches Python's `lzma.FORMAT_ALONE`. We rebuild the same stream using the
standard library and verify the 5-byte header against expectations.
"""
from __future__ import annotations

import lzma

# Defaults below mirror the Java encoder configuration as best as Python's lzma
# module allows. The MF choice (BT2 vs BT4) cannot be set to BT2 in Python; we use
# BT4 (compatible decoder behavior; only encoder choice affects ratio, not stream
# decodability — the printer decoder only reads the LZMA1 properties header).
DEFAULT_FILTERS = [
    {
        "id": lzma.FILTER_LZMA1,
        "dict_size": 8192,
        "lc": 3,
        "lp": 0,
        "pb": 2,
        "mode": lzma.MODE_NORMAL,
        "mf": lzma.MF_BT4,
        "nice_len": 128,
    }
]


def lzma_encode_alone(data: bytes) -> bytes:
    """LZMA-Alone encode `data` with E10-compatible parameters.

    The output is the classic .lzma container:
        5-byte properties header + 8-byte LE64 uncompressed size + LZMA1 stream.

    Note: Python's stdlib writes 0xFFFFFFFFFFFFFFFF for the size (the "unknown"
    sentinel). The Android encoder writes the *actual* uncompressed length.
    We overwrite the field to match the Java encoder byte-for-byte, since the
    embedded firmware decoder may rely on a known size.
    """
    out = bytearray(lzma.compress(data, format=lzma.FORMAT_ALONE, filters=DEFAULT_FILTERS))
    out[5:13] = len(data).to_bytes(8, "little")
    return bytes(out)


def decode_lzma_header(stream: bytes) -> dict:
    """Decode the 5-byte LZMA1 properties header — useful for cross-checking
    that an on-wire stream matches what we expect.
    """
    if len(stream) < 13:
        raise ValueError("stream too short for LZMA-Alone container")
    d = stream[0]
    pb = d // 45
    rem = d % 45
    lp = rem // 9
    lc = rem - lp * 9
    dict_size = int.from_bytes(stream[1:5], "little")
    uncompressed = int.from_bytes(stream[5:13], "little")
    return {"lc": lc, "lp": lp, "pb": pb, "dict_size": dict_size,
            "uncompressed_size": uncompressed}
