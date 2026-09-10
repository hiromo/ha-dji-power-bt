"""Button platform for DJI Power."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .entity import DjiPowerEntity
from .manager import DjiPowerManager


@dataclass(frozen=True, slots=True)
class ButtonDescription:
    key: str
    name: str
    press_fn: Callable[[DjiPowerManager], object]
    icon: str
    enabled_default: bool = True
    entity_category: EntityCategory | None = None
    supported_fn: Callable[[DjiPowerManager], bool] | None = None
    available_fn: Callable[[DjiPowerManager], bool] | None = None
    translation_key: str | None = None


async def _start_payload_capture(manager: DjiPowerManager) -> None:
    await manager.async_start_payload_capture()


async def _set_all_day_peak_tariff(manager: DjiPowerManager) -> None:
    await manager.async_set_tariff_schedule(preset="all_day_peak")


async def _set_all_day_off_peak_tariff(manager: DjiPowerManager) -> None:
    await manager.async_set_tariff_schedule(preset="all_day_off_peak")


def _supports_power_2000_tariff_presets(manager: DjiPowerManager) -> bool:
    return manager.model_code == 0x94 and manager.capabilities.has_tariff_slots


BUTTONS: tuple[ButtonDescription, ...] = (
    ButtonDescription(
        "capture_payloads",
        "Capture protocol payloads",
        _start_payload_capture,
        "mdi:bug-play-outline",
        enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ButtonDescription(
        "set_all_day_peak_tariff",
        "Set all-day peak tariff",
        _set_all_day_peak_tariff,
        "mdi:weather-night",
        enabled_default=False,
        entity_category=EntityCategory.CONFIG,
        supported_fn=_supports_power_2000_tariff_presets,
        available_fn=lambda m: m.tariff_preset_control_available,
        translation_key="set_all_day_peak_tariff",
    ),
    ButtonDescription(
        "set_all_day_off_peak_tariff",
        "Set all-day off-peak tariff",
        _set_all_day_off_peak_tariff,
        "mdi:weather-sunny-alert",
        enabled_default=False,
        entity_category=EntityCategory.CONFIG,
        supported_fn=_supports_power_2000_tariff_presets,
        available_fn=lambda m: m.tariff_preset_control_available,
        translation_key="set_all_day_off_peak_tariff",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    manager: DjiPowerManager = entry.runtime_data
    async_add_entities(
        DjiPowerButton(manager, description)
        for description in BUTTONS
        if description.supported_fn is None or description.supported_fn(manager)
    )


class DjiPowerButton(DjiPowerEntity, ButtonEntity):
    """DJI Power button."""

    def __init__(self, manager: DjiPowerManager, description: ButtonDescription) -> None:
        super().__init__(manager, description.key, description.name)
        self.description = description
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = description.enabled_default
        self._attr_entity_category = description.entity_category
        self._attr_translation_key = description.translation_key

    @property
    def available(self) -> bool:
        if self.description.available_fn is not None:
            return self.description.available_fn(self.manager)
        return super().available

    async def async_press(self) -> None:
        await self.description.press_fn(self.manager)
        self.async_write_ha_state()
