"""Base entity helpers for DJI Power."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.helpers.entity import Entity

from .manager import DjiPowerManager


class DjiPowerEntity(Entity):
    """Base entity for one DJI Power Bluetooth config entry."""

    _attr_has_entity_name = True

    def __init__(self, manager: DjiPowerManager, key: str, name: str) -> None:
        self.manager = manager
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{manager.address}_{key}".replace(":", "_").lower()
        self._remove_listener: Callable[[], None] | None = None

    @property
    def device_info(self) -> dict[str, Any]:
        return self.manager.device_info

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self.manager.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @property
    def available(self) -> bool:
        return self.manager.state.connected and self.manager.state.authenticated
