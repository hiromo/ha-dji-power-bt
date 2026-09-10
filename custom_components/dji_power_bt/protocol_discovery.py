"""DJI Power BLE advertisement parsing."""
from __future__ import annotations

from dataclasses import dataclass

from .const import DJI_COMPANY_ID, MODEL_NAMES

@dataclass(frozen=True, slots=True)
class AdvertisementInfo:
    """DJI manufacturer-data fields used for discovery and model selection."""

    model_code: int
    model: str
    bound: bool
    mac_candidate: str | None
    raw_hex: str


def parse_manufacturer_data(value: bytes) -> AdvertisementInfo:
    """Parse a DJI Power manufacturer payload.

    Home Assistant normally removes the little-endian company ID (AA 08) from
    ``manufacturer_data[0x08AA]``. Some captured/raw sources retain it, so both
    forms are accepted. The observed payload layout is:
      byte 0: model code
      byte 1: flags (bit 0x10 means bound)
      bytes 3..8: MAC-address candidate
    """
    raw_value = value
    company_prefix = DJI_COMPANY_ID.to_bytes(2, "little")
    if value.startswith(company_prefix):
        value = value[2:]
    if len(value) < 2:
        raise ValueError("DJI manufacturer data is too short")
    model_code = value[0]
    flags = value[1]
    mac_candidate: str | None = None
    if len(value) >= 9:
        mac = value[3:9]
        if any(mac):
            mac_candidate = ":".join(f"{byte:02X}" for byte in mac)
    return AdvertisementInfo(
        model_code=model_code,
        model=MODEL_NAMES.get(model_code, f"DJI Power (0x{model_code:02X})"),
        bound=bool(flags & 0x10),
        mac_candidate=mac_candidate,
        raw_hex=raw_value.hex(" "),
    )

