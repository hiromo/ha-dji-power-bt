"""Diagnostics support for DJI Power."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, CONF_LOCAL_AUTH_KEY, CONF_SERIAL_NUMBER
from .manager_diagnostics import (
    domain_connection_runtime_snapshot, manager_runtime_snapshot,
)

_REDACTED = "**REDACTED**"
_TO_REDACT = {CONF_LOCAL_AUTH_KEY, CONF_SERIAL_NUMBER}
_MAC_PATTERN = re.compile(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}")


def _mask_address(value: object) -> object:
    """Mask the device-specific portion of a Bluetooth/MAC address."""
    if not isinstance(value, str):
        return value
    parts = value.replace("-", ":").split(":")
    if len(parts) != 6:
        return _REDACTED
    return ":".join((*parts[:3], "XX", "XX", "XX"))


def _mask_addresses_in_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    return _MAC_PATTERN.sub(lambda match: str(_mask_address(match.group(0))), value)


def _sanitize_connection_event(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(record)
    if "address" in sanitized:
        sanitized["address"] = _mask_address(sanitized["address"])
    if "exception_message" in sanitized:
        sanitized["exception_message"] = _mask_addresses_in_text(
            sanitized["exception_message"]
        )
    return sanitized


def _redact_known_identifier_tlv(payload_hex: str) -> str:
    """Redact top-level 0x100E device-identifier TLVs, preserving frame shape."""
    try:
        payload = bytearray.fromhex(payload_hex)
    except ValueError:
        return _REDACTED

    # 0x60/0x62 payloads can have a command-specific header before the keyed
    # records. Scan every offset instead of assuming the first byte is a TLV.
    marker = (0x100E).to_bytes(2, "little")
    pos = 0
    while pos + 4 <= len(payload):
        if payload[pos : pos + 2] != marker:
            pos += 1
            continue
        length = int.from_bytes(payload[pos + 2 : pos + 4], "little")
        value_start = pos + 4
        value_end = value_start + length
        if value_end > len(payload):
            pos += 1
            continue
        payload[value_start:value_end] = b"*" * length
        pos = value_end
    return payload.hex(" ")


def _sanitize_payload_record(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(record)
    payload_hex = sanitized.get("payload_hex")
    if isinstance(payload_hex, str):
        sanitized["payload_hex"] = _redact_known_identifier_tlv(payload_hex)
    return sanitized


def _sanitize_payload_mapping(
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {key: _sanitize_payload_record(value) for key, value in records.items()}


def _sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Remove raw base-identity bytes while retaining decoded firmware fields."""
    sanitized = dict(config)
    if sanitized.get("base_config_raw_hex") is not None:
        sanitized["base_config_raw_hex"] = _REDACTED
    return sanitized



async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return bounded diagnostics without credentials or direct identifiers."""
    data = async_redact_data(dict(entry.data), _TO_REDACT)
    if CONF_ADDRESS in data:
        data[CONF_ADDRESS] = _mask_address(data[CONF_ADDRESS])

    manager = getattr(entry, "runtime_data", None)
    state: dict[str, Any] = {}
    if manager is not None:
        state = manager_runtime_snapshot(manager)
        for key in (
            "configured_address",
            "resolved_ble_address",
            "advertised_mac_candidate",
        ):
            state[key] = _mask_address(state.get(key))

        if isinstance(state.get("config"), dict):
            state["config"] = _sanitize_config(state["config"])
        state["latest_safe_payloads"] = _sanitize_payload_mapping(
            state.get("latest_safe_payloads", {})
        )
        state["captured_safe_payloads"] = [
            _sanitize_payload_record(record)
            for record in state.get("captured_safe_payloads", [])
        ]
        state["connection_event_history"] = [
            _sanitize_connection_event(record)
            for record in state.get("connection_event_history", [])
        ]

        domain = domain_connection_runtime_snapshot(manager)
        if domain is not None:
            domain["managers"] = [
                {**item, "address": _mask_address(item.get("address"))}
                for item in domain.get("managers", [])
            ]
            domain["connection_event_history"] = [
                _sanitize_connection_event(record)
                for record in domain.get("connection_event_history", [])
            ]
        state["domain_connection_runtime"] = domain
        state["payload_security"] = {
            "authentication_command_0x6a_excluded": True,
            "pair_key_excluded": True,
            "member_token_not_persisted": True,
            "known_identifier_tlv_0x100e_redacted": True,
        }

    return {"entry": data, "state": state}
