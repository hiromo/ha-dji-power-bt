"""DJI Power Bluetooth custom integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DEVICE_ID,
    ATTR_DURATION_SECONDS,
    ATTR_END_TIME,
    ATTR_ENERGY_OPTIMIZATION_MODE,
    ATTR_MAX_FRAMES,
    ATTR_OFF_PEAK_CHARGING,
    ATTR_OFF_PEAK_CHARGING_POWER,
    ATTR_PEAK_DISCHARGING,
    ATTR_PERIODS,
    ATTR_PRESET,
    ATTR_START_TIME,
    ATTR_TARIFF,
    ATTR_WEEKDAYS,
    CONF_ADDRESS,
    DEFAULT_CAPTURE_DURATION_SECONDS,
    DEFAULT_CAPTURE_MAX_FRAMES,
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_SCHEDULED_ENERGY_SETTINGS,
    SERVICE_SET_TARIFF_SCHEDULE,
    SERVICE_START_PROTOCOL_CAPTURE,
)
from .manager import DjiPowerManager
from .protocol import (
    MAX_TARIFF_SLOTS,
    TARIFF_PRESET_OPTIONS,
    TARIFF_WEEKDAY_BITS,
    normalize_address,
)
from .runtime import get_domain_runtime


type DjiPowerConfigEntry = ConfigEntry[DjiPowerManager]

_SERVICE_CAPTURE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(
            ATTR_DURATION_SECONDS, default=DEFAULT_CAPTURE_DURATION_SECONDS
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
        vol.Optional(
            ATTR_MAX_FRAMES, default=DEFAULT_CAPTURE_MAX_FRAMES
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
    }
)


def _validate_scheduled_energy_settings(data: dict) -> dict:
    """Require at least one optional 0x1018 field."""
    fields = (
        ATTR_ENERGY_OPTIMIZATION_MODE,
        ATTR_PEAK_DISCHARGING,
        ATTR_OFF_PEAK_CHARGING,
        ATTR_OFF_PEAK_CHARGING_POWER,
    )
    if not any(field in data for field in fields):
        raise vol.Invalid("At least one scheduled energy setting is required")
    return data


_SERVICE_SCHEDULED_ENERGY_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,
            vol.Optional(ATTR_ENERGY_OPTIMIZATION_MODE): vol.In(
                {"disabled", "scheduled"}
            ),
            vol.Optional(ATTR_PEAK_DISCHARGING): cv.boolean,
            vol.Optional(ATTR_OFF_PEAK_CHARGING): cv.boolean,
            vol.Optional(ATTR_OFF_PEAK_CHARGING_POWER): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=10000)
            ),
        }
    ),
    _validate_scheduled_energy_settings,
)


def _validate_tariff_schedule_action(data: dict) -> dict:
    """Require exactly one complete tariff-schedule input form."""
    if (ATTR_PRESET in data) == (ATTR_PERIODS in data):
        raise vol.Invalid("Specify exactly one of preset or periods")
    return data


_TARIFF_PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TARIFF): vol.In({"peak", "off_peak"}),
        vol.Required(ATTR_WEEKDAYS): vol.All(
            cv.ensure_list,
            [vol.In(set(TARIFF_WEEKDAY_BITS))],
            vol.Length(min=1, max=7),
        ),
        vol.Required(ATTR_START_TIME): cv.string,
        vol.Required(ATTR_END_TIME): cv.string,
    }
)

_SERVICE_TARIFF_SCHEDULE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,
            vol.Optional(ATTR_PRESET): vol.In(set(TARIFF_PRESET_OPTIONS)),
            vol.Optional(ATTR_PERIODS): vol.All(
                cv.ensure_list,
                [_TARIFF_PERIOD_SCHEMA],
                vol.Length(min=1, max=MAX_TARIFF_SLOTS),
            ),
        }
    ),
    _validate_tariff_schedule_action,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide service actions."""

    def _manager_for_device(device_id: str) -> DjiPowerManager:
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            raise ServiceValidationError("DJI Power device was not found")

        runtime = get_domain_runtime(hass)
        manager = next(
            (
                runtime.managers[entry_id]
                for entry_id in device.config_entries
                if entry_id in runtime.managers
            ),
            None,
        )
        if manager is None:
            raise ServiceValidationError(
                "The selected DJI Power device is not currently loaded"
            )
        return manager

    async def _async_start_protocol_capture(call: ServiceCall) -> None:
        manager = _manager_for_device(call.data[ATTR_DEVICE_ID])
        await manager.async_start_payload_capture(
            duration_seconds=call.data[ATTR_DURATION_SECONDS],
            max_frames=call.data[ATTR_MAX_FRAMES],
        )

    async def _async_set_scheduled_energy_settings(call: ServiceCall) -> None:
        manager = _manager_for_device(call.data[ATTR_DEVICE_ID])
        await manager.async_set_scheduled_energy_settings(
            energy_optimization_mode=call.data.get(ATTR_ENERGY_OPTIMIZATION_MODE),
            peak_discharging=call.data.get(ATTR_PEAK_DISCHARGING),
            off_peak_charging=call.data.get(ATTR_OFF_PEAK_CHARGING),
            off_peak_charging_power=call.data.get(ATTR_OFF_PEAK_CHARGING_POWER),
        )

    async def _async_set_tariff_schedule(call: ServiceCall) -> None:
        manager = _manager_for_device(call.data[ATTR_DEVICE_ID])
        await manager.async_set_tariff_schedule(
            preset=call.data.get(ATTR_PRESET),
            periods=call.data.get(ATTR_PERIODS),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_PROTOCOL_CAPTURE,
        _async_start_protocol_capture,
        schema=_SERVICE_CAPTURE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULED_ENERGY_SETTINGS,
        _async_set_scheduled_energy_settings,
        schema=_SERVICE_SCHEDULED_ENERGY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TARIFF_SCHEDULE,
        _async_set_tariff_schedule,
        schema=_SERVICE_TARIFF_SCHEDULE_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DjiPowerConfigEntry) -> bool:
    """Set up one physical DJI Power device from one config entry."""
    runtime = get_domain_runtime(hass)
    address = normalize_address(entry.data[CONF_ADDRESS])

    for existing_entry_id, existing_manager in runtime.managers.items():
        if existing_entry_id != entry.entry_id and existing_manager.address == address:
            raise ConfigEntryNotReady(
                f"DJI Power BLE address {address} is already owned by another config entry"
            )

    manager = DjiPowerManager(
        hass,
        entry,
        connection_operation_lock=runtime.connection_operation_lock,
        domain_runtime=runtime,
    )
    entry.runtime_data = manager
    runtime.managers[entry.entry_id] = manager

    async def _async_stop_on_ha_stop(_event: Event) -> None:
        await manager.async_stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_on_ha_stop)
    )

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await manager.async_start()
    except Exception:
        runtime.managers.pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DjiPowerConfigEntry) -> bool:
    """Unload one DJI Power Bluetooth config entry."""
    manager = getattr(entry, "runtime_data", None)
    if manager is not None:
        await manager.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime = get_domain_runtime(hass)
    runtime.managers.pop(entry.entry_id, None)
    return unload_ok
