"""High-level E10 print orchestrator — implements the doPrint state machine.

State machine source: T15Print.doPrint (T15Print.java:103-320). Re-implemented
on top of the bleak transport.
"""
from __future__ import annotations

import asyncio
import logging
from PIL import Image

from .ble import E10Connection
from .compress import lzma_encode_alone
from .constants import (
    CMD_BLTCMD_SET_HEADRATE, CMD_BUF_FULL, CMD_INQUIRY_STA,
    CMD_NEXT_ZIPPEDBULK, CMD_PAPER_BACK, CMD_START_PRINT, CMD_STOP_PRINT,
    DEFAULT_THRESHOLD, DMA_BLE_SUBCHUNK_DELAY_S, DMA_PAGE_SIZE,
    E10_BYTES_PER_COLUMN, E10_HEAD_DOTS,
)
from .frame import (
    build_command_frame, build_command_frame_int_param,
    parse_frame_header, split_envelope_for_ble, split_into_dma_chunks,
    wrap_dma_envelope,
)
from .page import PageRegBits, build_pre_lzma_buffer
from .raster import fit_to_head, pack_bitmap
from .status import FstaFlags, MstaFlags, parse_fsta, parse_msta


log = logging.getLogger("katasym.protocol")


class E10Printer:
    """Higher-level wrapper over an `E10Connection`."""

    def __init__(self, conn: E10Connection):
        self.conn = conn

    # ---------------- handshake helpers ----------------

    async def inquiry_status(
        self,
        timeout: float = 1.0,
        with_response: bool = False,
        opcode: int = CMD_INQUIRY_STA,
    ) -> tuple[MstaFlags, FstaFlags] | None:
        """Send CMD_INQUIRY_STA and parse the response.

        Accumulates notify chunks until at least 18 bytes are received (the
        minimum to hold MSTA at [14-15] and FSTA at [16-17]).
        """
        self.conn.drain_notify()
        frame = build_command_frame_int_param(opcode, 0)
        if with_response:
            await self.conn.write(frame, response=True)
        else:
            await self.conn.write_no_response(frame)

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        buf = bytearray()
        while loop.time() < deadline:
            chunk = await self.conn.wait_notify(timeout=max(0.05, deadline - loop.time()))
            if chunk is None:
                break
            buf.extend(chunk)
            if len(buf) >= 18:
                break
        if not buf:
            return None
        return decode_status_reply(bytes(buf))

    async def set_density(self, concentration: int) -> None:
        """Send CMD_BLTCMD_SET_HEADRATE = 0xC9 with the scaled density value.

        T15Print.doPrint (T15Print.java:155) computes the wire value as
        `int(((concentration - 1) / 10 + 0.8) * 100)` which gives 80, 90, 100,
        110, 120, 130, 140 for concentration 1..7 — passed via the standard
        16-byte int-param frame (sendCmd(byte, int, byte[]) — the byte[] arg is
        the answer buffer, NOT the payload).
        """
        if not 1 <= concentration <= 7:
            raise ValueError("concentration must be in 1..7")
        scaled = int(((concentration - 1) / 10.0 + 0.8) * 100.0)
        await self.conn.write_no_response(
            build_command_frame_int_param(CMD_BLTCMD_SET_HEADRATE, scaled)
        )

    async def start_print(self, out_paper: int = 0) -> None:
        await self.conn.write_no_response(
            build_command_frame_int_param(CMD_START_PRINT, out_paper)
        )

    async def stop_print(self) -> None:
        await self.conn.write_no_response(
            build_command_frame_int_param(CMD_STOP_PRINT, 0)
        )

    async def paper_back(self, lines: int) -> None:
        await self.conn.write_no_response(
            build_command_frame_int_param(CMD_PAPER_BACK, lines)
        )

    async def buf_full(self) -> None:
        await self.conn.write_no_response(
            build_command_frame_int_param(CMD_BUF_FULL, 0)
        )

    # ---------------- raster transfer ----------------

    async def transfer_compressed_page(self, compressed: bytes) -> None:
        """Send a CMD_NEXT_ZIPPEDBULK frame followed by all DMA chunks.

        For E-class printers (E10), each 506-byte DMA chunk is wrapped in a
        512-byte outer envelope and split into 4×128-byte BLE writes with a
        50 ms inter-write delay (BasePrint.transferSplitData,
        BasePrint.java:857-887).
        """
        chunks = split_into_dma_chunks(compressed)
        # Init: 0x5C cmd with [page_size LE16][num_chunks LE16] as payload.
        # Mirroring sendCmdStartTrans(0x5C, 512, num_chunks, answer).
        init_payload = bytes([
            DMA_PAGE_SIZE & 0xFF, (DMA_PAGE_SIZE >> 8) & 0xFF,
            len(chunks) & 0xFF, (len(chunks) >> 8) & 0xFF,
        ])
        # sendCmd uses the standard prefix [0x00, 0x01] then the params:
        init_payload = bytes([0x00, 0x01]) + init_payload
        await self.conn.write_no_response(
            build_command_frame(CMD_NEXT_ZIPPEDBULK, init_payload)
        )
        for chunk in chunks:
            envelope = wrap_dma_envelope(chunk)
            for sub in split_envelope_for_ble(envelope):
                await asyncio.sleep(DMA_BLE_SUBCHUNK_DELAY_S)
                await self.conn.write_no_response(sub)

    # ---------------- high-level print ----------------

    async def print_image(
        self,
        img: Image.Image,
        concentration: int = 4,
        copies: int = 1,
        threshold: int = DEFAULT_THRESHOLD,
        cut_type: int = 0,
        first_cut: int = 0,
        save_paper: bool = False,
        out_paper: int = 0,
        paper_back_lines: int = 0,
        ready_timeout: float = 5.0,
    ) -> None:
        """End-to-end print of one image (the printer's narrow strip).

        The image's height is forced to 96 dots (the E10 head width); the image's
        width becomes the label length in dots.
        """
        # 1. wait device ready
        await self._wait_until_ready(ready_timeout)

        # 2. set density
        await self.set_density(concentration)
        await asyncio.sleep(0.05)

        # 3. build raster + pre-LZMA buffer + compress
        head = fit_to_head(img, E10_HEAD_DOTS)
        raster = pack_bitmap(head, threshold=threshold)
        column_count = head.size[0]
        page_reg = PageRegBits(
            page_st=1, page_end=1, prt_end=1,
            cut=cut_type, savepaper=int(save_paper),
            first_cut=first_cut, nodu=concentration & 0b11, mat=1,
        )
        pre = build_pre_lzma_buffer(
            raster, column_count=column_count, page_reg=page_reg,
            per_line_byte=E10_BYTES_PER_COLUMN, no_zero_index=0,
        )
        compressed = lzma_encode_alone(pre)

        # 4. start print job
        await self.start_print(out_paper=out_paper)
        # wait for FSTA.PrtSta == 1 (printer accepted the job)
        await self._wait_printing(ready_timeout)

        # 5. optional paper back
        if paper_back_lines:
            await self.paper_back(paper_back_lines)

        # 6. transfer each copy
        for _ in range(copies):
            await self.transfer_compressed_page(compressed)
            await self.buf_full()
            await asyncio.sleep(0.1)

        # 7. wait completion
        await self._wait_complete(ready_timeout)

    # ---------------- internal waits ----------------

    async def _wait_until_ready(self, timeout: float) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            status = await self.inquiry_status(timeout=0.3)
            if status is None:
                await asyncio.sleep(0.1)
                continue
            msta, _ = status
            if msta.com_exe_sta == 0 and msta.buf_sta == 0:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError("printer never reached ready state")

    async def _wait_printing(self, timeout: float) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            status = await self.inquiry_status(timeout=0.3)
            if status is None:
                await asyncio.sleep(0.1)
                continue
            _, fsta = status
            if fsta.prt_sta == 1:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError("printer did not accept the print job")

    async def _wait_complete(self, timeout: float) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            status = await self.inquiry_status(timeout=0.3)
            if status is None:
                await asyncio.sleep(0.1)
                continue
            msta, fsta = status
            if fsta.prt_sta == 0 and msta.com_exe_sta == 0:
                return
            await asyncio.sleep(0.1)
        log.warning("print completion timed out after %.1fs", timeout)


# ---------------- response decoding ----------------

def decode_status_reply(buf: bytes) -> tuple[MstaFlags, FstaFlags] | None:
    """Parse a printer reply: validate header, decode MSTA/FSTA at the default offsets."""
    hdr = parse_frame_header(buf)
    if hdr is None:
        return None
    if len(buf) < 18:
        return None
    return parse_msta(buf, 14), parse_fsta(buf, 16)
