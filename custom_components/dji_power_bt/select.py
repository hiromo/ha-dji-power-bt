"""Select platform for DJI Power."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .entity import DjiPowerEntity
from .manager import DjiPowerManager


@dataclass(frozen=True, slots=True)
class SelectDescription:
    key: str
    name: str
    options_fn: Callable[[DjiPowerManager], list[str]]
    current_fn: Callable[[DjiPowerManager], str | None]
    select_fn: Callable[[DjiPowerManager, str], object]
    supported_fn: Callable[[DjiPowerManager], bool]
    available_fn: Callable[[DjiPowerManager], bool]
    icon: str | None = None


async def _set_energy_optimization(manager: DjiPowerManager, option: str) -> None:
    await manager.async_set_energy_optimization_mode(option)


async def _set_charging_mode(manager: DjiPowerManager, option: str) -> None:
    await manager.async_set_charging_mode(option)


SELECTS: tuple[SelectDescription, ...] = (
    SelectDescription(
        key="energy_optimization_mode",
        name="Energy optimization mode",
        options_fn=lambda _m: ["disabled", "scheduled"],
        current_fn=lambda m: (
            m.state.energy_optimization_mode
            if m.state.energy_optimization_mode in {"disabled", "scheduled"}
            else None
        ),
        select_fn=_set_energy_optimization,
        supported_fn=lambda m: m.capabilities.has_energy_optimization,
        available_fn=lambda m: m.energy_optimization_control_available,
        icon="mdi:home-lightning-bolt-outline",
    ),
    SelectDescription(
        key="charging_mode",
        name="Charging mode",
        options_fn=lambda m: m.charging_mode_options,
        current_fn=lambda m: m.state.charging_mode,
        select_fn=_set_charging_mode,
        supported_fn=lambda m: m.capabilities.has_charging_mode,
        available_fn=lambda m: bool(
            m.state.connected
            and m.state.authenticated
            and m.state.config is not None
            and m.state.config.charging_mode_write_supported
            and m.state.charging_mode in m.charging_mode_options
        ),
        icon="mdi:battery-charging-high",
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    manager: DjiPowerManager = entry.runtime_data
    async_add_entities(
        DjiPowerSelect(manager, description)
        for description in SELECTS
        if description.supported_fn(manager)
    )


class DjiPowerSelect(DjiPowerEntity, SelectEntity):
    """DJI Power enumerated setting."""

    def __init__(self, manager: DjiPowerManager, description: SelectDescription) -> None:
        super().__init__(manager, description.key, description.name)
        self.description = description
        if description.icon:
            self._attr_icon = description.icon

    @property
    def options(self) -> list[str]:
        return self.description.options_fn(self.manager)

    @property
    def current_option(self) -> str | None:
        return self.description.current_fn(self.manager)

    @property
    def available(self) -> bool:
        return super().available and self.description.available_fn(self.manager)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "last_write_result": self.manager.state.last_write_result,
            "reflection_confirmed": self.manager.state.reflection_confirmed,
            "reflection_source": self.manager.state.reflection_source,
        }
        cfg = self.manager.state.config
        if self.description.key == "energy_optimization_mode" and cfg is not None:
            attrs.update(
                {
                    "raw_mode": cfg.energy_saver_raw,
                    "decoded_mode": cfg.energy_optimization_mode,
                    "control_supported": cfg.energy_optimization_mode
                    in {"disabled", "scheduled"},
                }
            )
        if self.description.key == "charging_mode" and cfg is not None:
            attrs["modes"] = [item.as_dict() for item in cfg.charging_modes]
        return attrs

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise HomeAssistantError(f"Unsupported option: {option}")
        await self.description.select_fn(self.manager, option)
        self.async_write_ha_state()
