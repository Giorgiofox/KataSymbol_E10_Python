"""MSTA/FSTA register decoders matching PRINTER_FLAG.Refresh in the app.

For T15-family printers (default offset map):
    response[14:16] -> MSTA (2 bytes)
    response[16:18] -> FSTA (2 bytes)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MstaFlags:
    buf_sta: int     # 0=ready, 1=busy
    lab_rw_err: int
    lab_end: int
    lab_xh_err: int
    rib_rw_err: int
    rib_end: int
    rib_xh_err: int
    chk_mat_ok: int
    sys_err: int
    com_exe_sta: int
    cut_need_clr: int
    dev_clr_sta: int


@dataclass
class FstaFlags:
    f_b1_sta: int
    f_b2_sta: int
    f_b3_sta: int
    cover_open: int
    rib_end: int
    lab_end: int
    prt_sta: int     # 1=printing
    s_dev_busy: int
    lab_fix_err: int
    q_cut_err: int
    s_tube_fix_err: int
    s_tube_end: int
    b_cut_err: int
    rib_fix_err: int


def parse_msta(buf: bytes, offset: int = 14) -> MstaFlags:
    b0, b1 = buf[offset], buf[offset + 1]
    return MstaFlags(
        buf_sta=int(bool(b0 & 0x01)),
        lab_rw_err=int(bool(b0 & 0x02)),
        lab_end=int(bool(b0 & 0x04)),
        lab_xh_err=int(bool(b0 & 0x08)),
        rib_rw_err=int(bool(b0 & 0x10)),
        rib_end=int(bool(b0 & 0x20)),
        rib_xh_err=int(bool(b0 & 0x40)),
        chk_mat_ok=int(bool(b0 & 0x80)),
        sys_err=int(bool(b1 & 0x03)),
        com_exe_sta=int(bool(b1 & 0x04)),
        cut_need_clr=int(bool(b1 & 0x08)),
        dev_clr_sta=int(bool(b1 & 0x10)),
    )


def parse_fsta(buf: bytes, offset: int = 16) -> FstaFlags:
    b0, b1 = buf[offset], buf[offset + 1]
    return FstaFlags(
        f_b1_sta=int(bool(b0 & 0x01)),
        f_b2_sta=int(bool(b0 & 0x02)),
        f_b3_sta=int(bool(b0 & 0x04)),
        cover_open=int(bool(b0 & 0x08)),
        rib_end=int(bool(b0 & 0x10)),
        lab_end=int(bool(b0 & 0x20)),
        prt_sta=int(bool(b0 & 0x40)),
        s_dev_busy=int(bool(b0 & 0x80)),
        lab_fix_err=int(bool(b1 & 0x01)),
        q_cut_err=int(bool(b1 & 0x02)),
        s_tube_fix_err=int(bool(b1 & 0x04)),
        s_tube_end=int(bool(b1 & 0x08)),
        b_cut_err=int(bool(b1 & 0x10)),
        rib_fix_err=int(bool(b1 & 0x20)),
    )
