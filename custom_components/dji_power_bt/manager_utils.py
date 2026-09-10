"""Small side-effect-free manager helpers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def client_object_id(client: object | None) -> str | None:
    return f"0x{id(client):x}" if client is not None else None

def client_is_connected(client: object | None) -> bool | None:
    if client is None:
        return None
    try:
        return bool(getattr(client, "is_connected"))
    except Exception:
        return None

def classify_connection_exception(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if (
        "outofconnectionslots" in name
        or "out of connection slots" in message
        or "no connection slots" in message
    ):
        return "out_of_slots"
    if "notfound" in name or "not reachable" in message or "not available" in message:
        return "device_not_found"
    if "aborted" in name or "cancel" in message:
        return "connection_aborted"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in name:
        return "timeout"
    if "auth" in name or "authentication" in message:
        return "authentication"
    if "notify" in message:
        return "start_notify"
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None and cause is not exc:
        return classify_connection_exception(cause)
    return "other"


def safe_device_source(device: object) -> str | None:
    """Best-effort scanner source lookup for diagnostics."""
    try:
        from bleak_retry_connector import device_source
        return device_source(device)
    except Exception:
        return None
