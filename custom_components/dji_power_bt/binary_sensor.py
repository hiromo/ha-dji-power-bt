"""Binary sensor platform for DJI Power."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .entity import DjiPowerEntity
from .manager import DjiPowerManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    manager: DjiPowerManager = entry.runtime_data
    async_add_entities([DjiPowerBleConnectedBinarySensor(manager)])


class DjiPowerBleConnectedBinarySensor(DjiPowerEntity, BinarySensorEntity):
    """BLE connected binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, manager: DjiPowerManager) -> None:
        super().__init__(manager, "ble_connected", "BLE connected")

    @property
    def is_on(self) -> bool:
        return self.manager.state.connected and self.manager.state.authenticated

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "ble_enabled": self.manager.state.ble_enabled,
            "authenticated": self.manager.state.authenticated,
            "last_error": self.manager.state.last_error,
            "last_disconnect_reason": self.manager.state.last_disconnect_reason,
            "last_disconnect_at": self.manager.state.last_disconnect_at,
            "last_connection_error": self.manager.state.last_connection_error,
            "last_connection_error_at": self.manager.state.last_connection_error_at,
            "last_gatt_connect_at": self.manager.state.last_gatt_connect_at,
            "last_ready_at": self.manager.state.last_ready_at,
            "gatt_connect_count": self.manager.state.gatt_connect_count,
            "gatt_reconnect_count": self.manager.state.gatt_reconnect_count,
            "successful_reconnect_count": self.manager.state.successful_reconnect_count,
            "reconnect_count": self.manager.state.reconnect_count,
            "bluetooth_source": self.manager.state.bluetooth_source,
            "configured_address": self.manager.address,
            "resolved_ble_address": self.manager.state.resolved_ble_address,
            "resolved_ble_name": self.manager.state.resolved_ble_name,
            "advertised_name": self.manager.state.advertised_name,
            "manufacturer_ids": [
                f"0x{value:04X}" for value in self.manager.state.manufacturer_ids
            ],
            "identity_status": self.manager.state.identity_status,
        }
