"""Switch platform for DJI Power."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .capabilities import RuntimeFeature
from .entity import DjiPowerEntity
from .manager import DjiPowerManager


@dataclass(frozen=True, slots=True)
class SwitchDescription:
    key: str
    name: str
    is_on_fn: Callable[[DjiPowerManager], bool | None]
    set_fn: Callable[[DjiPowerManager, bool], object]
    icon: str | None = None
    device_class: SwitchDeviceClass | None = None
    available_when_disconnected: bool = False
    supported_fn: Callable[[DjiPowerManager], bool] | None = None
    available_fn: Callable[[DjiPowerManager], bool] | None = None


async def _set_off_peak(manager: DjiPowerManager, value: bool) -> None:
    await manager.async_set_off_peak_charge_enabled(value)


async def _set_peak(manager: DjiPowerManager, value: bool) -> None:
    await manager.async_set_peak_discharge_enabled(value)


async def _set_ac_output(manager: DjiPowerManager, value: bool) -> None:
    await manager.async_set_ac_output_enabled(value)


async def _set_sdc(manager: DjiPowerManager, value: bool) -> None:
    await manager.async_set_sdc_enabled(value)


async def _set_ble(manager: DjiPowerManager, value: bool) -> None:
    await manager.async_set_ble_enabled(value)


SWITCHES: tuple[SwitchDescription, ...] = (
    SwitchDescription(
        key="off_peak_charging",
        name="Off-peak charging",
        is_on_fn=lambda m: m.state.off_peak_charge_enabled,
        set_fn=_set_off_peak,
        icon="mdi:battery-arrow-up",
        supported_fn=lambda m: m.capabilities.has_off_peak_charging,
        available_fn=lambda m: m.is_runtime_feature_available(
            RuntimeFeature.OFF_PEAK_CHARGING
        ),
    ),
    SwitchDescription(
        key="peak_discharging",
        name="Peak discharging",
        is_on_fn=lambda m: m.state.peak_discharge_enabled,
        set_fn=_set_peak,
        icon="mdi:battery-arrow-down",
        supported_fn=lambda m: m.capabilities.has_peak_discharging,
        available_fn=lambda m: m.is_runtime_feature_available(
            RuntimeFeature.PEAK_DISCHARGING
        ),
    ),
    SwitchDescription(
        key="ac_output",
        name="AC output",
        is_on_fn=lambda m: m.state.ac_output_enabled,
        set_fn=_set_ac_output,
        icon="mdi:power-socket-jp",
        supported_fn=lambda m: m.capabilities.has_ac_output,
    ),
    SwitchDescription(
        key="sdc",
        name="SDC",
        is_on_fn=lambda m: m.state.sdc_enabled,
        set_fn=_set_sdc,
        icon="mdi:current-dc",
        supported_fn=lambda m: m.capabilities.has_sdc_control,
    ),
    SwitchDescription(
        key="ble",
        name="BLE",
        is_on_fn=lambda m: m.state.ble_enabled,
        set_fn=_set_ble,
        icon="mdi:bluetooth",
        available_when_disconnected=True,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    manager: DjiPowerManager = entry.runtime_data
    async_add_entities(
        DjiPowerSwitch(manager, description)
        for description in SWITCHES
        if description.supported_fn is None or description.supported_fn(manager)
    )


class DjiPowerSwitch(DjiPowerEntity, SwitchEntity):
    """DJI Power switch."""

    def __init__(self, manager: DjiPowerManager, description: SwitchDescription) -> None:
        super().__init__(manager, description.key, description.name)
        self.description = description
        if description.icon:
            self._attr_icon = description.icon
        if description.device_class:
            self._attr_device_class = description.device_class

    @property
    def is_on(self) -> bool | None:
        return self.description.is_on_fn(self.manager)

    @property
    def available(self) -> bool:
        if self.description.available_when_disconnected:
            return True
        if self.description.available_fn is not None and not self.description.available_fn(
            self.manager
        ):
            return False
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "last_write_result": self.manager.state.last_write_result,
            "reflection_confirmed": self.manager.state.reflection_confirmed,
            "reflection_source": self.manager.state.reflection_source,
        }
        return attrs

    async def async_turn_on(self, **kwargs) -> None:
        await self.description.set_fn(self.manager, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.description.set_fn(self.manager, False)
        self.async_write_ha_state()
