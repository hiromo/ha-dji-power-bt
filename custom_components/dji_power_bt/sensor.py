"""Sensor platform for DJI Power."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_point_in_time

from .capabilities import RuntimeFeature
from .entity import DjiPowerEntity
from .manager import DjiPowerManager
from .protocol import classify_tariff_schedule
from .tariff import TariffPeriodStatus, evaluate_tariff_period


@dataclass(frozen=True, slots=True)
class SensorDescription:
    key: str
    name: str
    value_fn: Callable[[DjiPowerManager], Any]
    device_class: SensorDeviceClass | None = None
    native_unit: str | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    icon: str | None = None
    available_fn: Callable[[DjiPowerManager], bool] | None = None
    attrs_fn: Callable[[DjiPowerManager], dict[str, Any]] | None = None
    supported_fn: Callable[[DjiPowerManager], bool] | None = None
    enabled_default: bool = True
    enabled_default_fn: Callable[[DjiPowerManager], bool] | None = None
    entity_category: EntityCategory | None = None
    allow_none_when_available: bool = False


def _power(key: str, name: str, value_fn, **kwargs) -> SensorDescription:
    return SensorDescription(
        key=key,
        name=name,
        value_fn=value_fn,
        device_class=SensorDeviceClass.POWER,
        native_unit=UnitOfPower.WATT,
        **kwargs,
    )


def _telemetry_available(manager: DjiPowerManager) -> bool:
    return (
        manager.state.connected
        and manager.state.authenticated
        and manager.state.metrics.power_telemetry_present
    )


def _port_power(key: str, name: str, value_fn, supported_fn) -> SensorDescription:
    return _power(
        key,
        name,
        value_fn,
        supported_fn=supported_fn,
        enabled_default=False,
        available_fn=_telemetry_available,
        allow_none_when_available=True,
    )


SENSORS: tuple[SensorDescription, ...] = (
    SensorDescription(
        key="soc",
        name="SoC",
        value_fn=lambda m: m.state.soc_percent,
        device_class=SensorDeviceClass.BATTERY,
        native_unit=PERCENTAGE,
        attrs_fn=lambda m: {
            "soc_duplicate_percent_candidate": m.state.metrics.soc_duplicate_percent_candidate,
            "battery_unit_count": m.state.metrics.battery_unit_count,
        },
    ),
    _power("input_power", "Input power", lambda m: m.state.input_power_w),
    _power("output_power", "Output power", lambda m: m.state.output_power_w),
    _power(
        "ac_input_power",
        "AC input power",
        lambda m: m.state.ac_input_power_w,
    ),
    _power(
        "ac_output_power",
        "AC output power",
        lambda m: m.state.ac_output_power_w,
        supported_fn=lambda m: m.capabilities.has_ac_output,
    ),
    # USB-A and USB-C share one protocol group. The group totals are the normal
    # user-facing aggregate; interface and port details remain in diagnostics.
    _power(
        "usb_input_power",
        "USB input power",
        lambda m: m.state.metrics.usb_input_power_w,
        supported_fn=lambda m: (m.capabilities.usb_a_ports + m.capabilities.usb_c_ports) > 0,
        enabled_default=False,
        enabled_default_fn=lambda m: m.capabilities.usb_c_input,
    ),
    _power(
        "usb_output_power",
        "USB output power",
        lambda m: m.state.metrics.usb_output_power_w,
        supported_fn=lambda m: (m.capabilities.usb_a_ports + m.capabilities.usb_c_ports) > 0,
    ),
    _port_power(
        "usb_a_1_output_power",
        "USB-A1 output power",
        lambda m: m.state.metrics.usb_a_1_output_power_w,
        lambda m: m.capabilities.usb_a_ports >= 1,
    ),
    _port_power(
        "usb_a_2_output_power",
        "USB-A2 output power",
        lambda m: m.state.metrics.usb_a_2_output_power_w,
        lambda m: m.capabilities.usb_a_ports >= 2,
    ),
    _port_power(
        "usb_a_3_output_power",
        "USB-A3 output power",
        lambda m: m.state.metrics.usb_a_3_output_power_w,
        lambda m: m.capabilities.usb_a_ports >= 3,
    ),
    _port_power(
        "usb_a_4_output_power",
        "USB-A4 output power",
        lambda m: m.state.metrics.usb_a_4_output_power_w,
        lambda m: m.capabilities.usb_a_ports >= 4,
    ),
    _port_power(
        "usb_c_1_input_power",
        "USB-C1 input power",
        lambda m: m.state.metrics.usb_c_1_input_power_w,
        lambda m: m.capabilities.usb_c_input and m.capabilities.usb_c_ports >= 1,
    ),
    _port_power(
        "usb_c_1_output_power",
        "USB-C1 output power",
        lambda m: m.state.metrics.usb_c_1_output_power_w,
        lambda m: m.capabilities.usb_c_ports >= 1,
    ),
    _port_power(
        "usb_c_2_input_power",
        "USB-C2 input power",
        lambda m: m.state.metrics.usb_c_2_input_power_w,
        lambda m: m.capabilities.usb_c_input and m.capabilities.usb_c_ports >= 2,
    ),
    _port_power(
        "usb_c_2_output_power",
        "USB-C2 output power",
        lambda m: m.state.metrics.usb_c_2_output_power_w,
        lambda m: m.capabilities.usb_c_ports >= 2,
    ),
    _port_power(
        "usb_c_3_input_power",
        "USB-C3 input power",
        lambda m: m.state.metrics.usb_c_3_input_power_w,
        lambda m: m.capabilities.usb_c_input and m.capabilities.usb_c_ports >= 3,
    ),
    _port_power(
        "usb_c_3_output_power",
        "USB-C3 output power",
        lambda m: m.state.metrics.usb_c_3_output_power_w,
        lambda m: m.capabilities.usb_c_ports >= 3,
    ),
    _port_power(
        "usb_c_4_input_power",
        "USB-C4 input power",
        lambda m: m.state.metrics.usb_c_4_input_power_w,
        lambda m: m.capabilities.usb_c_input and m.capabilities.usb_c_ports >= 4,
    ),
    _port_power(
        "usb_c_4_output_power",
        "USB-C4 output power",
        lambda m: m.state.metrics.usb_c_4_output_power_w,
        lambda m: m.capabilities.usb_c_ports >= 4,
    ),
    _power(
        "sdc_input_power",
        "SDC input power",
        lambda m: m.state.metrics.sdc_input_power_w,
        supported_fn=lambda m: m.capabilities.has_sdc,
    ),
    _power(
        "sdc_output_power",
        "SDC output power",
        lambda m: m.state.metrics.sdc_output_power_w,
        supported_fn=lambda m: m.capabilities.has_sdc,
    ),
    _port_power(
        "sdc_1_input_power",
        "SDC1 input power",
        lambda m: m.state.metrics.sdc_1_input_power_w,
        lambda m: m.capabilities.sdc_ports >= 1,
    ),
    _port_power(
        "sdc_1_output_power",
        "SDC1 output power",
        lambda m: m.state.metrics.sdc_1_output_power_w,
        lambda m: m.capabilities.sdc_ports >= 1,
    ),
    _port_power(
        "sdc_2_input_power",
        "SDC2 input power",
        lambda m: m.state.metrics.sdc_2_input_power_w,
        lambda m: m.capabilities.sdc_ports >= 2,
    ),
    _port_power(
        "sdc_2_output_power",
        "SDC2 output power",
        lambda m: m.state.metrics.sdc_2_output_power_w,
        lambda m: m.capabilities.sdc_ports >= 2,
    ),
    _power(
        "sdc_lite_input_power",
        "SDC Lite input power",
        lambda m: m.state.metrics.sdc_lite_input_power_w,
        supported_fn=lambda m: m.capabilities.has_sdc_lite,
        enabled_default=False,
    ),
    _power(
        "sdc_lite_output_power",
        "SDC Lite output power",
        lambda m: m.state.metrics.sdc_lite_output_power_w,
        supported_fn=lambda m: m.capabilities.has_sdc_lite,
        enabled_default=False,
    ),
    _power(
        "12v_output_power",
        "12 V output power",
        lambda m: m.state.metrics.output_12v_power_w,
        supported_fn=lambda m: m.capabilities.has_12v_accessory,
        enabled_default=False,
    ),
    _power(
        "xt60_input_power",
        "XT60 input power",
        lambda m: m.state.metrics.xt60_input_power_w,
        supported_fn=lambda m: m.capabilities.has_xt60_accessory,
        enabled_default=False,
    ),
    _power(
        "xt60_output_power",
        "XT60 output power",
        lambda m: m.state.metrics.xt60_output_power_w,
        supported_fn=lambda m: m.capabilities.has_xt60_accessory,
        enabled_default=False,
    ),
    SensorDescription(
        key="battery_temperature",
        name="Battery temperature",
        value_fn=lambda m: m.state.battery_temperature_c,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
    ),
    SensorDescription(
        key="battery_status_code",
        name="Battery status code",
        value_fn=lambda m: m.state.metrics.battery_status_code,
        state_class=None,
        icon="mdi:battery-heart-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled_default=False,
        attrs_fn=lambda m: {
            "raw_0x3010_hex": m.state.metrics.raw_0x3010_hex,
            "raw_0x3020_hex": m.state.metrics.raw_0x3020_hex,
            "raw_0x3050_hex": m.state.metrics.raw_0x3050_hex,
            "temperature_c": m.state.metrics.battery_temperature_c,
            "input_power_w": m.state.metrics.input_power_w,
            "output_power_w": m.state.metrics.output_power_w,
        },
    ),
    SensorDescription(
        key="remaining_time",
        name="Remaining time",
        value_fn=lambda m: m.state.remaining_time_min,
        native_unit=UnitOfTime.MINUTES,
        icon="mdi:timer-outline",
    ),
    SensorDescription(
        key="firmware",
        name="Firmware",
        value_fn=lambda m: m.state.config.firmware if m.state.config else None,
        state_class=None,
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled_default=False,
    ),
    SensorDescription(
        key="communication_module_firmware",
        name="Communication module firmware",
        value_fn=lambda m: (
            m.state.config.communication_module_firmware
            if m.state.config
            else None
        ),
        state_class=None,
        icon="mdi:access-point",
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled_default=False,
        attrs_fn=lambda _m: {"dji_home_label": "Dongle version"},
    ),
    SensorDescription(
        key="last_notify",
        name="Last notify",
        value_fn=lambda m: m.state.last_notify_at,
        state_class=None,
        icon="mdi:clock-outline",
        available_fn=lambda m: True,
        enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        attrs_fn=lambda m: {
            "last_0x61": m.state.last_0x61_at,
            "last_0x62": m.state.last_0x62_at,
            "last_0x66": m.state.last_0x66_at,
            "last_0x60_refresh": m.state.last_0x60_refresh_at,
            "last_write_result": m.state.last_write_result,
            "reflection_confirmed": m.state.reflection_confirmed,
            "reflection_source": m.state.reflection_source,
            "write_verification_pending": m.state.write_verification_pending,
            "last_write_sequence": m.state.last_write_sequence,
            "last_write_property": m.state.last_write_property,
            "last_error": m.state.last_error,
            "last_disconnect_reason": m.state.last_disconnect_reason,
            "last_disconnect_at": m.state.last_disconnect_at,
            "last_connection_error": m.state.last_connection_error,
            "last_connection_error_at": m.state.last_connection_error_at,
            "last_gatt_connect_at": m.state.last_gatt_connect_at,
            "last_ready_at": m.state.last_ready_at,
            "gatt_connect_count": m.state.gatt_connect_count,
            "gatt_reconnect_count": m.state.gatt_reconnect_count,
            "successful_reconnect_count": m.state.successful_reconnect_count,
            "reconnect_count": m.state.reconnect_count,
            "telemetry_update_interval_s": m.telemetry_update_interval,
            "bluetooth_source": m.state.bluetooth_source,
            "configured_address": m.address,
            "resolved_ble_address": m.state.resolved_ble_address,
            "resolved_ble_name": m.state.resolved_ble_name,
            "advertised_name": m.state.advertised_name,
            "advertised_model": m.state.advertised_model,
            "advertised_model_code": m.state.advertised_model_code,
            "manufacturer_ids": [f"0x{value:04X}" for value in m.state.manufacturer_ids],
            "identity_status": m.state.identity_status,
            "payload_capture": m.payload_capture_info,
        },
    ),
    SensorDescription(
        key="tariff_time_slots",
        name="Tariff time slots",
        value_fn=lambda m: len(m.state.config.tariff_slots)
        if m.state.config
        else None,
        state_class=None,
        icon="mdi:calendar-clock",
        enabled_default=False,
        supported_fn=lambda m: m.capabilities.has_tariff_slots,
        available_fn=lambda m: m.is_runtime_feature_available(
            RuntimeFeature.TARIFF_TIME_SLOTS
        ),
        attrs_fn=lambda m: {
            "slots": [slot.as_dict() for slot in m.state.config.tariff_slots]
            if m.state.config
            else None,
            "preset_match": classify_tariff_schedule(m.state.config.tariff_slots)
            if m.state.config
            else None,
            "summary": m.state.config.tariff_summary if m.state.config else None,
            "timezone_offset_min": m.state.config.timezone_offset_min
            if m.state.config
            else None,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    manager: DjiPowerManager = entry.runtime_data
    entities = [
        DjiPowerSensor(manager, description)
        for description in SENSORS
        if description.supported_fn is None or description.supported_fn(manager)
    ]
    if manager.capabilities.has_tariff_slots:
        entities.append(DjiPowerTariffPeriodSensor(manager))
    async_add_entities(entities)


class DjiPowerSensor(DjiPowerEntity, SensorEntity):
    def __init__(self, manager: DjiPowerManager, description: SensorDescription) -> None:
        super().__init__(manager, description.key, description.name)
        self.description = description
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit
        self._attr_state_class = description.state_class
        self._attr_entity_registry_enabled_default = (
            description.enabled_default_fn(manager)
            if description.enabled_default_fn is not None
            else description.enabled_default
        )
        self._attr_entity_category = description.entity_category
        if description.icon:
            self._attr_icon = description.icon

    @property
    def native_value(self) -> Any:
        return self.description.value_fn(self.manager)

    @property
    def available(self) -> bool:
        if self.description.available_fn is not None:
            available = self.description.available_fn(self.manager)
        else:
            available = super().available
        if self.description.allow_none_when_available:
            return available
        return available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.description.attrs_fn is None:
            return None
        return self.description.attrs_fn(self.manager)


class DjiPowerTariffPeriodSensor(DjiPowerEntity, SensorEntity):
    """Current tariff period calculated in the DJI Power device timezone."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["disabled", "peak", "off_peak", "none", "unknown"]
    _attr_translation_key = "tariff_period"
    _attr_icon = "mdi:clock-time-four-outline"
    _attr_state_class = None

    def __init__(self, manager: DjiPowerManager) -> None:
        super().__init__(manager, "tariff_period", "Tariff period")
        self._period = self._calculate_period()
        self._cancel_next_change = None

    def _device_now(self) -> datetime | None:
        cfg = self.manager.state.config
        if cfg is None or cfg.timezone_offset_min is None:
            return None
        device_tz = timezone(timedelta(minutes=cfg.timezone_offset_min))
        return datetime.now(timezone.utc).astimezone(device_tz)

    def _calculate_scheduled_period(self) -> TariffPeriodStatus:
        cfg = self.manager.state.config
        device_now = self._device_now()
        if cfg is None or device_now is None:
            return evaluate_tariff_period(None, datetime.now(timezone.utc))
        return evaluate_tariff_period(cfg.tariff_slots, device_now)

    def _calculate_period(self) -> TariffPeriodStatus:
        cfg = self.manager.state.config
        if cfg is None:
            return evaluate_tariff_period(None, datetime.now(timezone.utc))
        if cfg.energy_optimization_mode == "disabled":
            return TariffPeriodStatus(
                state="disabled",
                active_slot=None,
                next_change=None,
                next_period=None,
                conflict=False,
                valid=True,
            )
        if cfg.energy_optimization_mode != "scheduled":
            return TariffPeriodStatus(
                state="unknown",
                active_slot=None,
                next_change=None,
                next_period=None,
                conflict=False,
                valid=False,
            )
        return self._calculate_scheduled_period()

    @property
    def native_value(self) -> str:
        return self._period.state

    @property
    def available(self) -> bool:
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self.manager.state.config
        slots = cfg.tariff_slots if cfg else None
        scheduled_period = self._calculate_scheduled_period()
        return {
            "active_slot": self._period.active_slot,
            "next_change": self._period.next_change.isoformat()
            if self._period.next_change
            else None,
            "next_period": self._period.next_period,
            "slots": [slot.as_dict() for slot in slots] if slots is not None else None,
            "conflict": self._period.conflict,
            "source": "0x1017",
            "energy_optimization_mode": (
                cfg.energy_optimization_mode if cfg else "unknown"
            ),
            "scheduled_period": scheduled_period.state,
            "schedule_active": bool(
                cfg and cfg.energy_optimization_mode == "scheduled"
            ),
            "timezone_offset_min": cfg.timezone_offset_min if cfg else None,
            "timezone_source": "device_0x1015" if cfg and cfg.timezone_offset_min is not None else "unavailable",
        }

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self.manager.async_add_listener(self._handle_manager_update)
        self._schedule_next_change()

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_next_change is not None:
            self._cancel_next_change()
            self._cancel_next_change = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_manager_update(self) -> None:
        self._period = self._calculate_period()
        self._schedule_next_change()
        self.async_write_ha_state()

    @callback
    def _handle_time_change(self, _now) -> None:
        self._period = self._calculate_period()
        self._schedule_next_change()
        self.async_write_ha_state()

    @callback
    def _schedule_next_change(self) -> None:
        if self._cancel_next_change is not None:
            self._cancel_next_change()
            self._cancel_next_change = None
        if self._period.next_change is not None:
            self._cancel_next_change = async_track_point_in_time(
                self.hass,
                self._handle_time_change,
                self._period.next_change.astimezone(timezone.utc),
            )
