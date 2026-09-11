"""State and exception types for the DJI Power manager."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .protocol import HmsReport, PowerConfig, RealtimeMetrics
from .write_policy import WriteVerificationPolicy

class DjiPowerAuthError(HomeAssistantError):
    """Authentication failed."""


class DjiPowerConnectionError(HomeAssistantError):
    """Connection failed."""


@dataclass(slots=True)
class GattTrafficStats:
    """Bounded, payload-free counters since manager setup."""

    write_attempts_by_command: dict[str, int] = field(default_factory=dict)
    write_completions_by_command: dict[str, int] = field(default_factory=dict)
    write_lock_timeout_count: int = 0
    backend_write_timeout_count: int = 0
    write_waiters: int = 0
    max_write_waiters: int = 0
    max_write_lock_wait_s: float = 0.0
    max_backend_write_s: float = 0.0
    ack_scheduled_count: int = 0
    max_pending_ack_tasks: int = 0
    unchanged_write_skip_count: int = 0
    stale_notification_count: int = 0
    stale_write_rejected_count: int = 0



@dataclass(slots=True)
class PendingVerification:
    key: str
    revision: int
    expected: dict[str, Any]
    baseline_generation: int
    ack_sequence: int
    acknowledged_at: str
    history_record: dict[str, Any]
    policy: WriteVerificationPolicy


@dataclass(slots=True)
class DjiPowerState:
    connected: bool = False
    ble_enabled: bool = True
    authenticated: bool = False
    last_error: str | None = None

    last_notify_at: str | None = None
    last_0x61_at: str | None = None
    last_0x62_at: str | None = None
    last_0x66_at: str | None = None
    last_0x60_refresh_at: str | None = None
    last_write_result: str | None = None
    last_write_ack_at: str | None = None
    last_write_sequence: int | None = None
    last_write_property: str | None = None
    reflection_confirmed: bool | None = None
    reflection_source: str | None = None
    write_verification_pending: bool = False
    config_read_request_count: int = 0
    config_cache_hit_count: int = 0
    verification_readback_count: int = 0
    passive_verification_timeout_count: int = 0
    last_gatt_connect_at: str | None = None
    last_ready_at: str | None = None
    last_disconnect_reason: str | None = None
    last_disconnect_at: str | None = None
    last_connection_error: str | None = None
    last_connection_error_at: str | None = None
    last_connection_failure_category: str | None = None
    last_connection_failure_phase: str | None = None
    gatt_connect_count: int = 0
    gatt_reconnect_count: int = 0
    successful_reconnect_count: int = 0
    bluetooth_source: str | None = None
    consecutive_connect_failures: int = 0
    last_retry_delay_s: float | None = None
    last_device_resolution: str | None = None
    connection_phase: str = "idle"
    gatt_write_timeout_count: int = 0
    last_gatt_write_timeout_at: str | None = None
    stale_connection_cleanup_count: int = 0
    last_stale_connection_cleanup_at: str | None = None

    # Identity diagnostics. Device selection is always by exact BLE address;
    # advertised/user-visible names are diagnostic only.
    connector_name: str | None = None
    resolved_ble_address: str | None = None
    resolved_ble_name: str | None = None
    advertised_name: str | None = None
    advertisement_source: str | None = None
    manufacturer_ids: tuple[int, ...] = ()
    advertised_model_code: int | None = None
    advertised_model: str | None = None
    advertised_bound: bool | None = None
    advertised_mac_candidate: str | None = None
    identity_status: str | None = None

    config: PowerConfig | None = None
    metrics: RealtimeMetrics = field(default_factory=RealtimeMetrics)
    latest_hms_report: HmsReport | None = None

    @property
    def last_connect_at(self) -> str | None:
        """Backward-compatible alias for last GATT client adoption time."""
        return self.last_gatt_connect_at

    @last_connect_at.setter
    def last_connect_at(self, value: str | None) -> None:
        self.last_gatt_connect_at = value

    @property
    def reconnect_count(self) -> int:
        """Backward-compatible alias for GATT reconnect attempts."""
        return self.gatt_reconnect_count

    @reconnect_count.setter
    def reconnect_count(self, value: int) -> None:
        self.gatt_reconnect_count = value

    @property
    def soc_percent(self) -> float | None:
        return self.metrics.soc_percent

    @property
    def input_power_w(self) -> int | None:
        return self.metrics.input_power_w

    @property
    def output_power_w(self) -> int | None:
        return self.metrics.output_power_w

    @property
    def ac_input_power_w(self) -> int | None:
        """Power entering the device through its AC inlet."""
        return self.metrics.ac_inlet_input_power_w

    @property
    def ac_output_power_w(self) -> int | None:
        """Power leaving the device through its AC outlet bank."""
        return self.metrics.ac_outlet_output_power_w

    @property
    def battery_temperature_c(self) -> float | None:
        return self.metrics.battery_temperature_c

    @property
    def remaining_time_min(self) -> int | None:
        return self.metrics.remaining_time_min

    @property
    def off_peak_charging_power_w(self) -> int | None:
        return self.config.off_peak_charging_power_w if self.config else None

    @property
    def off_peak_charge_power_min_w(self) -> int | None:
        return self.config.off_peak_charge_power_min_w if self.config else None

    @property
    def off_peak_charge_power_max_w(self) -> int | None:
        return self.config.off_peak_charge_power_max_w if self.config else None

    @property
    def charge_limit_percent(self) -> int | None:
        return self.config.charge_limit_percent if self.config else None

    @property
    def charge_limit_min_percent(self) -> int | None:
        return self.config.charge_limit_min_percent if self.config else None

    @property
    def charge_limit_max_percent(self) -> int | None:
        return self.config.charge_limit_max_percent if self.config else None

    @property
    def discharge_limit_percent(self) -> int | None:
        return self.config.discharge_limit_percent if self.config else None

    @property
    def discharge_limit_min_percent(self) -> int | None:
        return self.config.discharge_limit_min_percent if self.config else None

    @property
    def discharge_limit_max_percent(self) -> int | None:
        return self.config.discharge_limit_max_percent if self.config else None

    @property
    def off_peak_charge_enabled(self) -> bool | None:
        return self.config.off_peak_charge_enabled if self.config else None

    @property
    def peak_discharge_enabled(self) -> bool | None:
        return self.config.peak_discharge_enabled if self.config else None

    @property
    def ac_output_enabled(self) -> bool | None:
        return self.config.ac_output_enabled if self.config else None

    @property
    def sdc_enabled(self) -> bool | None:
        return self.config.sdc_enabled if self.config else None

    @property
    def energy_optimization_mode(self) -> str:
        return self.config.energy_optimization_mode if self.config else "unknown"

    @property
    def charging_mode(self) -> str | None:
        return self.config.charging_mode if self.config else None
