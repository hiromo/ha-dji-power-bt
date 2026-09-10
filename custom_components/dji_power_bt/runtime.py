"""Shared runtime data for all DJI Power config entries."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

if TYPE_CHECKING:
    from .manager import DjiPowerManager

_CONNECTION_EVENT_HISTORY_LIMIT = 100


@dataclass(slots=True)
class DjiPowerDomainRuntime:
    """Runtime shared by every DJI Power Bluetooth config entry.

    Each physical device owns an independent manager and BLE connection. Connection
    setup/teardown operations are serialized, while a domain-wide event history makes
    it possible to correlate two devices when one connection affects another.
    """

    managers: dict[str, "DjiPowerManager"] = field(default_factory=dict)
    connection_operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connection_event_history: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=_CONNECTION_EVENT_HISTORY_LIMIT)
    )
    connection_lock_holder: str | None = None
    connection_lock_waiters: int = 0
    _next_connection_event_id: int = 1
    _next_connection_attempt_id: int = 1

    def next_connection_attempt_id(self) -> int:
        """Allocate a domain-wide connection-attempt identifier."""
        value = self._next_connection_attempt_id
        self._next_connection_attempt_id += 1
        return value

    def record_connection_event(self, event: dict[str, Any]) -> int:
        """Append one event to the bounded cross-device connection history."""
        event_id = self._next_connection_event_id
        self._next_connection_event_id += 1
        record = dict(event)
        record["event_id"] = event_id
        self.connection_event_history.append(record)
        return event_id


@callback
def get_domain_runtime(hass: HomeAssistant) -> DjiPowerDomainRuntime:
    """Return or create the shared DJI Power runtime."""
    runtime = hass.data.get(DOMAIN)
    if isinstance(runtime, DjiPowerDomainRuntime):
        return runtime

    runtime = DjiPowerDomainRuntime()
    hass.data[DOMAIN] = runtime
    return runtime
