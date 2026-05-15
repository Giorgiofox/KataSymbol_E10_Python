"""BLE transport for the Katasymbol E10 — thin wrapper around `bleak`.

Picks the correct service/characteristic set by short-form UUID substring,
mirroring BLEUtils.getService() in the app.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .constants import (
    CHAR_UUID_FEC1, CHAR_NOTIFY_FFE1, CHAR_WRITE_FFE9,
    CHAR_NOTIFY_FF01, CHAR_WRITE_FF02,
    DEFAULT_MTU_REQUEST, E10_SERIALS,
)


log = logging.getLogger("katasym.ble")


@dataclass
class FoundPrinter:
    address: str
    name: str
    rssi: int | None
    serial: str          # leading T00xx serial extracted from the adv name

    @property
    def display(self) -> str:
        return f"E10 {self.serial}"


def adv_serial(name: str | None) -> str | None:
    """Return the leading E10 serial (e.g. 'T0010') matched against the allowlist."""
    if not name or name.endswith("_BLE"):
        return None
    for s in E10_SERIALS:
        if name.startswith(s):
            return s
    return None


async def discover(timeout: float = 8.0,
                   only_e10: bool = True) -> list[FoundPrinter]:
    """Scan for BLE peripherals and return those whose name matches an E10 serial."""
    seen: dict[str, FoundPrinter] = {}

    def detection(dev: BLEDevice, adv: AdvertisementData) -> None:
        name = adv.local_name or dev.name
        serial = adv_serial(name)
        if only_e10 and not serial:
            return
        if dev.address in seen:
            return
        seen[dev.address] = FoundPrinter(
            address=dev.address,
            name=name or "",
            rssi=adv.rssi,
            serial=serial or (name or ""),
        )

    async with BleakScanner(detection_callback=detection) as _scanner:
        await asyncio.sleep(timeout)
    return list(seen.values())


class E10Connection:
    """Connected E10 over BLE: write helpers + notify queue."""

    def __init__(self, address: str):
        self.address = address
        self._client = BleakClient(address)
        self._write_uuid: str | None = None
        self._notify_uuid: str | None = None
        self._notify_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._notify_callback: Callable[[bytes], Awaitable[None]] | None = None

    async def __aenter__(self) -> "E10Connection":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        await self._client.connect()
        await self._pick_chars()
        if self._notify_uuid is None or self._write_uuid is None:
            raise RuntimeError("could not find a known E10 service set")
        await self._client.start_notify(self._notify_uuid, self._on_notify)
        log.info("connected to %s; write=%s notify=%s",
                 self.address, self._write_uuid, self._notify_uuid)

    async def _pick_chars(self) -> None:
        """Pick UUID set the same way BLEUtils.getService() does — substring match."""
        for svc in self._client.services:
            uuid_lc = str(svc.uuid).lower()
            if "fee7" in uuid_lc:
                self._write_uuid = self._notify_uuid = CHAR_UUID_FEC1
                return
            if uuid_lc.startswith("0000e0ff"):
                self._write_uuid = CHAR_WRITE_FFE9
                self._notify_uuid = CHAR_NOTIFY_FFE1
                return
            if "ff00" in uuid_lc:
                self._write_uuid = CHAR_WRITE_FF02
                self._notify_uuid = CHAR_NOTIFY_FF01
                return

    def _on_notify(self, _sender, data: bytearray) -> None:
        log.debug("RX %dB %s", len(data), bytes(data).hex())
        self._notify_q.put_nowait(bytes(data))
        if self._notify_callback:
            asyncio.create_task(self._notify_callback(bytes(data)))

    async def close(self) -> None:
        try:
            if self._notify_uuid:
                await self._client.stop_notify(self._notify_uuid)
        except Exception:
            pass
        await self._client.disconnect()

    # --- writes ---

    async def write(self, data: bytes, response: bool = False) -> None:
        if self._write_uuid is None:
            raise RuntimeError("not connected")
        await self._client.write_gatt_char(self._write_uuid, data, response=response)

    async def write_no_response(self, data: bytes) -> None:
        await self.write(data, response=False)

    # --- notify drain helpers ---

    async def wait_notify(self, timeout: float = 1.0) -> bytes | None:
        try:
            return await asyncio.wait_for(self._notify_q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def drain_notify(self) -> None:
        while not self._notify_q.empty():
            self._notify_q.get_nowait()

    # --- introspection ---

    @property
    def mtu(self) -> int:
        try:
            return self._client.mtu_size
        except Exception:
            return DEFAULT_MTU_REQUEST
