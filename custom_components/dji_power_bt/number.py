"""Number platform for DJI Power."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .capabilities import RuntimeFeature
from .entity import DjiPowerEntity
from .manager import DjiPowerManager


@dataclass(frozen=True, slots=True)
class NumberDescription:
    key: str
    name: str
    value_fn: Callable[[DjiPowerManager], int | None]
    min_fn: Callable[[DjiPowerManager], int]
    max_fn: Callable[[DjiPowerManager], int]
    step_fn: Callable[[DjiPowerManager], int]
    set_fn: Callable[[DjiPowerManager, int], object]
    native_unit: str
    device_class: NumberDeviceClass | None = None
    icon: str | None = None
    supported_fn: Callable[[DjiPowerManager], bool] | None = None
    available_fn: Callable[[DjiPowerManager], bool] | None = None


async def _set_off_peak_power(manager: DjiPowerManager, value: int) -> None:
    await manager.async_set_off_peak_power(value)


async def _set_charge_limit(manager: DjiPowerManager, value: int) -> None:
    await manager.async_set_charge_limit(value)


async def _set_discharge_limit(manager: DjiPowerManager, value: int) -> None:
    await manager.async_set_discharge_limit(value)


NUMBERS: tuple[NumberDescription, ...] = (
    NumberDescription(
        key="off_peak_charging_power",
        name="Off-peak charging power",
        value_fn=lambda m: m.state.off_peak_charging_power_w,
        min_fn=lambda m: m.state.off_peak_charge_power_min_w or 600,
        max_fn=lambda m: m.state.off_peak_charge_power_max_w or 1500,
        step_fn=lambda m: m.off_peak_charging_power_step_w,
        set_fn=_set_off_peak_power,
        native_unit=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        supported_fn=lambda m: m.capabilities.has_off_peak_charging,
        available_fn=lambda m: m.is_runtime_feature_available(
            RuntimeFeature.OFF_PEAK_CHARGING_POWER
        ),
    ),
    NumberDescription(
        key="charge_limit",
        name="Charge limit",
        value_fn=lambda m: m.state.charge_limit_percent,
        min_fn=lambda m: m.state.charge_limit_min_percent or 70,
        max_fn=lambda m: m.state.charge_limit_max_percent or 100,
        step_fn=lambda m: 1,
        set_fn=_set_charge_limit,
        native_unit=PERCENTAGE,
        icon="mdi:battery-arrow-up-outline",
        supported_fn=lambda m: m.capabilities.has_charge_limits,
    ),
    NumberDescription(
        key="discharge_limit",
        name="Discharge limit",
        value_fn=lambda m: m.state.discharge_limit_percent,
        min_fn=lambda m: m.state.discharge_limit_min_percent or 0,
        max_fn=lambda m: m.state.discharge_limit_max_percent or 15,
        step_fn=lambda m: 1,
        set_fn=_set_discharge_limit,
        native_unit=PERCENTAGE,
        icon="mdi:battery-arrow-down-outline",
        supported_fn=lambda m: m.capabilities.has_charge_limits,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    manager: DjiPowerManager = entry.runtime_data
    async_add_entities(
        DjiPowerNumber(manager, description)
        for description in NUMBERS
        if description.supported_fn is None or description.supported_fn(manager)
    )


class DjiPowerNumber(DjiPowerEntity, NumberEntity):
    """DJI Power numeric setting."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, manager: DjiPowerManager, description: NumberDescription) -> None:
        super().__init__(manager, description.key, description.name)
        self.description = description
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit
        if description.icon:
            self._attr_icon = description.icon

    @property
    def native_min_value(self) -> float:
        return float(self.description.min_fn(self.manager))

    @property
    def native_max_value(self) -> float:
        return float(self.description.max_fn(self.manager))

    @property
    def native_step(self) -> float:
        return float(self.description.step_fn(self.manager))

    @property
    def native_value(self) -> float | None:
        value = self.description.value_fn(self.manager)
        return float(value) if value is not None else None

    @property
    def available(self) -> bool:
        if self.description.available_fn is not None and not self.description.available_fn(
            self.manager
        ):
            return False
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "last_write_result": self.manager.state.last_write_result,
            "reflection_confirmed": self.manager.state.reflection_confirmed,
            "reflection_source": self.manager.state.reflection_source,
        }
        if self.description.key == "off_peak_charging_power":
            attrs["configured_step_w"] = self.manager.off_peak_charging_power_step_w
            attrs["step_source"] = "model_profile"
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        target = int(round(value))
        min_value = int(self.native_min_value)
        max_value = int(self.native_max_value)
        step = int(self.native_step)
        if not (min_value <= target <= max_value):
            raise HomeAssistantError(f"Value must be between {min_value} and {max_value}")
        if step > 1 and (target - min_value) % step != 0:
            raise HomeAssistantError(f"Value must follow a {step} W step from {min_value} W")
        await self.description.set_fn(self.manager, target)
        self.async_write_ha_state()
