"""Shared low-level DJI Power protocol helpers and interface names."""
from __future__ import annotations

import re

INTERFACE_TYPE_NAMES: dict[int, str] = {0: "unknown", 1: "ac_inlet", 2: "ac_outlet", 3: "usb_a", 4: "usb_c", 5: "sdc", 6: "sdc_lite", 7: "12v", 8: "xt60"}
GROUP_TYPE_NAMES: dict[int, str] = {0: "unknown", 1: "ac_inlet", 2: "ac_outlet", 3: "usb", 4: "sdc", 5: "12v", 6: "xt60"}

def normalize_address(address: str) -> str:
    return address.replace("-", ":").upper()

def validate_local_auth_key(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{32}", value or ""):
        raise ValueError("local auth key must be 32 ASCII hex characters")
    return value.lower()

def u16le(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=False)

def u32le(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=False)
