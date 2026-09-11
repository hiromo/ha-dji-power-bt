"""Home Assistant-facing manager for one DJI Power device.

The manager keeps the public control API and owns shared state. Connection,
transport and payload-capture internals are split into focused mixins.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Callable
import logging
from typing import Any
import weakref

from bleak import BleakClient
from bleak.backends.device import BLEDevice

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_ADDRESS, CONF_DEVICE_NAME, CONF_LOCAL_AUTH_KEY, CONF_MODEL, CONF_MODEL_CODE,
    CONF_SCAN_TIMEOUT, CONF_TELEMETRY_UPDATE_INTERVAL, DEFAULT_CAPTURE_DURATION_SECONDS,
    DEFAULT_CAPTURE_MAX_FRAMES, DEFAULT_SCAN_TIMEOUT, DEFAULT_TELEMETRY_UPDATE_INTERVAL,
    DOMAIN,
)
from .capabilities import (
    RuntimeFeature, capabilities_for_model_code, infer_model_code, model_name_for_code,
)
from .manager_connection import ManagerConnectionMixin
from .manager_constants import (
    CONFIG_CACHE_MAX_AGE_SECONDS, CONNECTION_EVENT_HISTORY_LIMIT,
    HMS_PATTERN_HISTORY_LIMIT, OUTPUT_TABLE_CACHE_MAX_AGE_SECONDS,
)
from .manager_payload import ManagerPayloadMixin
from .manager_transport import ManagerTransportMixin
from .manager_types import (
    DjiPowerAuthError, DjiPowerConnectionError, DjiPowerState, GattTrafficStats,
    PendingVerification,
)
from .manager_utils import classify_connection_exception as _classify_connection_exception
from .manager_utils import utcnow_iso
from .protocol import (
    DumlFrame, DumlReassembler, PowerConfig, build_0x63_1005_payload_from_config,
    build_0x63_charging_mode_payload_from_config, build_0x63_output_payload_from_config,
    build_0x63_payload_from_config, build_0x63_tariff_schedule_payload,
    make_tariff_slots_from_periods, make_tariff_slots_from_preset,
    normalize_address, update_0x1005_charge_limit, update_0x1005_discharge_limit,
    update_0x1018_energy_optimization_mode, update_0x1018_off_peak_charge_enabled,
    update_0x1018_off_peak_power, update_0x1018_peak_discharge_enabled,
    tariff_schedule_signature, validate_local_auth_key,
)
from .write_policy import (
    ACTIVE_WRITE_VERIFICATION, OFF_PEAK_POWER_WRITE_VERIFICATION, snapshot_is_fresh,
)

_LOGGER = logging.getLogger(__name__)


class DjiPowerManager(ManagerConnectionMixin, ManagerPayloadMixin, ManagerTransportMixin):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        connection_operation_lock: asyncio.Lock,
        domain_runtime: Any | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.address = normalize_address(entry.data[CONF_ADDRESS])
        self.device_name = entry.data.get(CONF_DEVICE_NAME) or entry.title
        stored_code = entry.data.get(CONF_MODEL_CODE)
        self.model_code = (
            int(stored_code)
            if isinstance(stored_code, int)
            else infer_model_code(entry.data.get(CONF_MODEL))
        )
        self.model = model_name_for_code(self.model_code)
        self.local_auth_key = validate_local_auth_key(entry.data[CONF_LOCAL_AUTH_KEY])
        self.scan_timeout = float(entry.data.get(CONF_SCAN_TIMEOUT, DEFAULT_SCAN_TIMEOUT))
        self.telemetry_update_interval = float(
            entry.options.get(
                CONF_TELEMETRY_UPDATE_INTERVAL,
                entry.data.get(
                    CONF_TELEMETRY_UPDATE_INTERVAL,
                    DEFAULT_TELEMETRY_UPDATE_INTERVAL,
                ),
            )
        )
        self.capabilities = capabilities_for_model_code(self.model_code)
        # Never pass the user-visible name to the connection layer. This stable
        # label is for logs only and cannot collide when two devices share a name.
        self.connector_name = f"DJI Power [{self.address}]"

        self.state = DjiPowerState(
            ble_enabled=True,
            connector_name=self.connector_name,
        )

        self._listeners: list[Callable[[], None]] = []
        self._pending: dict[tuple[int, int], tuple[int, int, asyncio.Future[DumlFrame]]] = {}
        self._connection_generation = 0
        self._reassembler = DumlReassembler()
        self._client: BleakClient | None = None
        self._retired_client: BleakClient | None = None
        self._expected_disconnect_client_ids: dict[
            int, tuple[weakref.ReferenceType[BleakClient], float]
        ] = {}
        self._last_ble_device: BLEDevice | None = None
        self._last_notify_monotonic: float | None = None
        self._ever_connected = False
        self._ever_ready = False
        self._retry_wakeup = asyncio.Event()
        self._runner_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._connect_lock = asyncio.Lock()
        self._connection_operation_lock = connection_operation_lock
        self._domain_runtime = domain_runtime
        self._write_lock = asyncio.Lock()
        self._gatt_traffic = GattTrafficStats()
        self._write_lock_acquired_monotonic: float | None = None
        self._write_lock_context: str | None = None
        self._operation_lock = asyncio.Lock()
        self._transport_unhealthy_reason: str | None = None
        self._next_seq = 0x2711
        self._config_generation = 0
        self._last_config_report_monotonic: float | None = None
        self._unconfirmed_config_writes: dict[int, str] = {}
        self._verification_revisions: dict[str, int] = {}
        self._pending_verifications: dict[str, PendingVerification] = {}
        self._verification_tasks: dict[str, asyncio.Task[None]] = {}
        self._write_history: deque[dict[str, Any]] = deque(maxlen=20)
        self._telemetry_publish_timer: asyncio.TimerHandle | None = None
        self._last_telemetry_publish_monotonic: float | None = None
        self._telemetry_publish_pending = False
        self._latest_payloads: dict[str, dict[str, Any]] = {}
        self._capture_frames: deque[dict[str, Any]] = deque()
        self._capture_active_until_monotonic: float | None = None
        self._capture_max_frames = DEFAULT_CAPTURE_MAX_FRAMES
        self._capture_started_at: str | None = None
        self._capture_finished_at: str | None = None
        self._ack_tasks: set[asyncio.Task[None]] = set()
        self._hms_pattern_history: deque[dict[str, Any]] = deque(
            maxlen=HMS_PATTERN_HISTORY_LIMIT
        )
        self._hms_full_parse_count = 0
        self._hms_fast_path_hit_count = 0
        self._last_hms_body: bytes | None = None
        self._cached_device_retry_used = False
        self._last_stale_cleanup_failure_count = 0
        self._local_connection_event_history: deque[dict[str, Any]] = deque(
            maxlen=CONNECTION_EVENT_HISTORY_LIMIT
        )
        self._local_next_connection_event_id = 1
        self._local_next_connection_attempt_id = 1
        self._active_connection_attempt_id: int | None = None
        self._active_connection_attempt_started_monotonic: float | None = None
        self._active_connection_failure_phase: str | None = None
        self._unexpected_disconnect_monotonic: float | None = None
        self._reconnect_not_before_monotonic: float | None = None
        self._fresh_advertisement_required = False
        self._fresh_advertisement_received_at: str | None = None

    async def async_start(self) -> None:
        if self._runner_task and not self._runner_task.done():
            return
        self._stopping = False
        self._record_connection_event("manager_start")
        self._runner_task = self.hass.loop.create_task(self._run_loop())

    async def async_stop(self) -> None:
        """Stop reconnect loop and release the BLE connection as cleanly as possible."""
        self._stopping = True
        self._record_connection_event("manager_stop_requested")
        self._cancel_write_verifications()
        self._cancel_ack_tasks()
        self._cancel_telemetry_publish()
        await self._cancel_runner_task()
        await self.async_disconnect(reason="stop")
        self._record_connection_event("manager_stopped")

    async def _cancel_runner_task(self) -> None:
        task = self._runner_task
        self._runner_task = None
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update_callback)

        def remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    @property
    def off_peak_charging_power_step_w(self) -> int:
        """Return the verified model-profile step for numeric off-peak power."""
        step = self.capabilities.off_peak_charging_power_step_w
        if step is None or step <= 0:
            raise HomeAssistantError(
                "Off-peak charging power step is not defined for this model"
            )
        return step

    @property
    def charging_mode_options(self) -> list[str]:
        cfg = self.state.config
        if cfg is None:
            return []
        return [
            item.key for item in cfg.charging_modes if item.key in {"slow", "fast"}
        ]

    @property
    def energy_optimization_control_available(self) -> bool:
        cfg = self.state.config
        return bool(
            self.state.connected
            and self.state.authenticated
            and self.capabilities.has_energy_optimization
            and cfg is not None
            and cfg.tlv_1018_value is not None
            and cfg.energy_optimization_mode in {"disabled", "scheduled"}
        )

    @property
    def tariff_preset_control_available(self) -> bool:
        """Return whether the captured Power 2000 tariff writer is available."""
        return bool(
            self.state.connected
            and self.state.authenticated
            and self.model_code == 0x94
            and self.capabilities.has_tariff_slots
            and self.state.config is not None
        )

    def is_runtime_feature_available(self, feature: RuntimeFeature) -> bool:
        if not self.state.connected or not self.state.authenticated:
            return False
        scheduled_features = {
            RuntimeFeature.OFF_PEAK_CHARGING,
            RuntimeFeature.PEAK_DISCHARGING,
            RuntimeFeature.OFF_PEAK_CHARGING_POWER,
            RuntimeFeature.TARIFF_PERIOD,
            RuntimeFeature.TARIFF_TIME_SLOTS,
        }
        if feature in scheduled_features:
            return self.state.energy_optimization_mode == "scheduled"
        return True

    def _require_scheduled_energy_mode(self) -> None:
        mode = self.state.energy_optimization_mode
        if mode != "scheduled":
            raise HomeAssistantError(
                "This setting can only be changed while Energy optimization is "
                f"set to Scheduled periods (current mode: {mode})"
            )

    # ------------------------------------------------------------------
    # Public controls used by entities
    # ------------------------------------------------------------------

    async def async_set_ble_enabled(self, enabled: bool) -> None:
        self._record_connection_event(
            "ble_control_changed", details={"enabled": enabled}
        )
        self.state.ble_enabled = enabled
        self._notify_listeners()
        if not enabled:
            self._stopping = True
            self._retry_wakeup.set()
            await self._cancel_runner_task()
            await self.async_disconnect(reason="manual_disable")
            return

        # Manual reconnect is also an operator-requested circuit-breaker reset.
        self.state.consecutive_connect_failures = 0
        self.state.last_retry_delay_s = None
        self._retry_wakeup.set()
        if not self._runner_task or self._runner_task.done():
            await self.async_start()

    async def async_manual_disconnect(self) -> None:
        await self.async_set_ble_enabled(False)

    async def async_manual_reconnect(self) -> None:
        await self.async_set_ble_enabled(True)

    async def async_set_scheduled_energy_settings(
        self,
        *,
        energy_optimization_mode: str | None = None,
        peak_discharging: bool | None = None,
        off_peak_charging: bool | None = None,
        off_peak_charging_power: int | None = None,
    ) -> None:
        """Update multiple known 0x1018 fields in one read-modify-write."""
        if all(
            value is None
            for value in (
                energy_optimization_mode,
                peak_discharging,
                off_peak_charging,
                off_peak_charging_power,
            )
        ):
            raise HomeAssistantError(
                "At least one scheduled energy setting is required"
            )

        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1018,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_1018_bulk_prewrite",
            )
            if cfg.tlv_1018_value is None:
                raise HomeAssistantError("0x1018 TLV not available")
            if cfg.energy_optimization_mode not in {"disabled", "scheduled"}:
                raise HomeAssistantError(
                    "The device is using an unsupported energy optimization mode; "
                    "change it with DJI Home before controlling it from Home Assistant"
                )

            effective_mode = (
                energy_optimization_mode
                if energy_optimization_mode is not None
                else cfg.energy_optimization_mode
            )
            scheduled_fields_requested = any(
                value is not None
                for value in (
                    peak_discharging,
                    off_peak_charging,
                    off_peak_charging_power,
                )
            )
            if scheduled_fields_requested and effective_mode != "scheduled":
                raise HomeAssistantError(
                    "Peak discharging, off-peak charging, and off-peak charging "
                    "power can only be changed when the resulting Energy "
                    "optimization mode is Scheduled periods"
                )

            new_1018 = cfg.tlv_1018_value
            changed_fields: set[str] = set()

            if energy_optimization_mode is not None:
                updated = update_0x1018_energy_optimization_mode(
                    new_1018, energy_optimization_mode
                )
                if updated != new_1018:
                    changed_fields.add("energy_optimization_mode")
                new_1018 = updated

            if peak_discharging is not None:
                updated = update_0x1018_peak_discharge_enabled(
                    new_1018, peak_discharging
                )
                if updated != new_1018:
                    changed_fields.add("peak_discharging")
                new_1018 = updated

            if off_peak_charging is not None:
                updated = update_0x1018_off_peak_charge_enabled(
                    new_1018, off_peak_charging
                )
                if updated != new_1018:
                    changed_fields.add("off_peak_charging")
                new_1018 = updated

            if off_peak_charging_power is not None:
                updated = update_0x1018_off_peak_power(
                    new_1018,
                    int(off_peak_charging_power),
                    step_w=self.off_peak_charging_power_step_w,
                )
                if updated != new_1018:
                    changed_fields.add("off_peak_charging_power")
                new_1018 = updated

            # A repeated automation call with an already matching target must not
            # generate another full 0x1018 transaction.
            if self._skip_unchanged_config_write(0x1018, not changed_fields):
                return

            payload = build_0x63_payload_from_config(cfg, new_1018)
            verification_policy = (
                OFF_PEAK_POWER_WRITE_VERIFICATION
                if changed_fields == {"off_peak_charging_power"}
                or (
                    not changed_fields
                    and off_peak_charging_power is not None
                    and energy_optimization_mode is None
                    and peak_discharging is None
                    and off_peak_charging is None
                )
                else ACTIVE_WRITE_VERIFICATION
            )
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1018,
                verification_key="scheduled_energy_settings",
                expected_off_peak_power=(
                    int(off_peak_charging_power)
                    if off_peak_charging_power is not None
                    else None
                ),
                expected_off_peak_enabled=off_peak_charging,
                expected_peak_enabled=peak_discharging,
                expected_energy_mode=energy_optimization_mode,
                new_1018_value=new_1018,
                verification_policy=verification_policy,
            )

    async def async_set_off_peak_power(self, value_w: int) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1018,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_1018_prewrite",
            )
            self._require_scheduled_energy_mode()
            if cfg.tlv_1018_value is None:
                raise HomeAssistantError("0x1018 TLV not available")
            new_1018 = update_0x1018_off_peak_power(
                cfg.tlv_1018_value,
                int(value_w),
                step_w=self.off_peak_charging_power_step_w,
            )
            if self._skip_unchanged_config_write(
                0x1018, new_1018 == cfg.tlv_1018_value
            ):
                return
            payload = build_0x63_payload_from_config(cfg, new_1018)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1018,
                verification_key="off_peak_charging_power",
                expected_off_peak_power=int(value_w),
                new_1018_value=new_1018,
                verification_policy=OFF_PEAK_POWER_WRITE_VERIFICATION,
            )

    async def async_set_charge_limit(self, value_percent: int) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1005,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_1005_prewrite",
            )
            if cfg.tlv_1005_value is None:
                raise HomeAssistantError("0x1005 TLV not available")
            new_1005 = update_0x1005_charge_limit(cfg.tlv_1005_value, int(value_percent))
            if self._skip_unchanged_config_write(
                0x1005, new_1005 == cfg.tlv_1005_value
            ):
                return
            payload = build_0x63_1005_payload_from_config(cfg, new_1005)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1005,
                verification_key="charge_limit",
                expected_charge_limit=int(value_percent),
                new_1005_value=new_1005,
            )

    async def async_set_discharge_limit(self, value_percent: int) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1005,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_1005_prewrite",
            )
            if cfg.tlv_1005_value is None:
                raise HomeAssistantError("0x1005 TLV not available")
            new_1005 = update_0x1005_discharge_limit(cfg.tlv_1005_value, int(value_percent))
            if self._skip_unchanged_config_write(
                0x1005, new_1005 == cfg.tlv_1005_value
            ):
                return
            payload = build_0x63_1005_payload_from_config(cfg, new_1005)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1005,
                verification_key="discharge_limit",
                expected_discharge_limit=int(value_percent),
                new_1005_value=new_1005,
            )

    async def async_set_off_peak_charge_enabled(self, enabled: bool) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1018,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_1018_prewrite",
            )
            self._require_scheduled_energy_mode()
            if cfg.tlv_1018_value is None:
                raise HomeAssistantError("0x1018 TLV not available")
            new_1018 = update_0x1018_off_peak_charge_enabled(cfg.tlv_1018_value, enabled)
            if self._skip_unchanged_config_write(
                0x1018, new_1018 == cfg.tlv_1018_value
            ):
                return
            payload = build_0x63_payload_from_config(cfg, new_1018)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1018,
                verification_key="off_peak_charging",
                expected_off_peak_enabled=enabled,
                new_1018_value=new_1018,
            )

    async def async_set_peak_discharge_enabled(self, enabled: bool) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1018,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_1018_prewrite",
            )
            self._require_scheduled_energy_mode()
            if cfg.tlv_1018_value is None:
                raise HomeAssistantError("0x1018 TLV not available")
            new_1018 = update_0x1018_peak_discharge_enabled(cfg.tlv_1018_value, enabled)
            if self._skip_unchanged_config_write(
                0x1018, new_1018 == cfg.tlv_1018_value
            ):
                return
            payload = build_0x63_payload_from_config(cfg, new_1018)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1018,
                verification_key="peak_discharging",
                expected_peak_enabled=enabled,
                new_1018_value=new_1018,
            )

    async def async_set_output_interface_enabled(
        self, *, interface_type: int, port_index: int, enabled: bool
    ) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            # 0x100D behaves as a complete output-interface table. Reuse only a
            # recent device-reported table; otherwise refresh immediately before
            # changing one record so unrelated and future/unknown interfaces are
            # preserved.
            cfg = await self._config_for_write(
                required_tlv=0x100D,
                max_age_s=OUTPUT_TABLE_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_output_prewrite",
            )
            payload, updated_states = build_0x63_output_payload_from_config(
                cfg,
                interface_type=interface_type,
                port_index=port_index,
                enabled=enabled,
            )
            if self._skip_unchanged_config_write(
                0x100D, updated_states == cfg.output_interface_states
            ):
                return
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x100D,
                verification_key=f"output_{interface_type:02x}_{port_index}",
                expected_output=(interface_type, port_index, enabled),
                updated_output_states=updated_states,
            )

    async def async_set_ac_output_enabled(self, enabled: bool) -> None:
        await self.async_set_output_interface_enabled(
            interface_type=0x02, port_index=1, enabled=enabled
        )

    async def async_set_sdc_enabled(self, enabled: bool) -> None:
        await self.async_set_output_interface_enabled(
            interface_type=0x05, port_index=1, enabled=enabled
        )

    async def async_set_energy_optimization_mode(self, mode: str) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            cfg = await self._config_for_write(
                required_tlv=0x1018,
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_energy_mode_prewrite",
            )
            if cfg.energy_optimization_mode not in {"disabled", "scheduled"}:
                raise HomeAssistantError(
                    "The device is using an unsupported energy optimization mode; "
                    "change it with DJI Home before controlling it from Home Assistant"
                )
            if cfg.tlv_1018_value is None:
                raise HomeAssistantError("0x1018 TLV not available")
            new_1018 = update_0x1018_energy_optimization_mode(
                cfg.tlv_1018_value, mode
            )
            if self._skip_unchanged_config_write(
                0x1018, new_1018 == cfg.tlv_1018_value
            ):
                return
            payload = build_0x63_payload_from_config(cfg, new_1018)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1018,
                verification_key="energy_optimization",
                expected_energy_mode=mode,
                new_1018_value=new_1018,
            )

    async def async_set_charging_mode(self, mode: str) -> None:
        async with self._operation_lock:
            await self._ensure_ready()
            # 0x101E is also a complete selectable-mode table. Preserve every
            # record and only flip the selected-state bytes. A recent 0x62/0x60
            # snapshot is sufficient; stale or missing data is refreshed.
            cfg = await self._config_for_write(
                required_tlv=0x101E,
                max_age_s=OUTPUT_TABLE_CACHE_MAX_AGE_SECONDS,
                refresh_source="0x60_charging_mode_prewrite",
            )
            payload, updated_modes = build_0x63_charging_mode_payload_from_config(
                cfg, mode
            )
            if self._skip_unchanged_config_write(
                0x101E, updated_modes == cfg.charging_modes
            ):
                return
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x101E,
                verification_key="charging_mode",
                expected_charging_mode=mode,
                updated_charging_modes=updated_modes,
            )

    async def async_set_tariff_schedule(
        self,
        *,
        preset: str | None = None,
        periods: list[dict[str, Any]] | None = None,
    ) -> None:
        """Replace the complete tariff table from one preset or period list."""
        if (preset is None) == (periods is None):
            raise HomeAssistantError(
                "Specify exactly one of preset or periods for the tariff schedule"
            )
        try:
            updated_slots = (
                make_tariff_slots_from_preset(preset)
                if preset is not None
                else make_tariff_slots_from_periods(periods or [])
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        async with self._operation_lock:
            await self._ensure_ready()
            if self.model_code != 0x94 or not self.capabilities.has_tariff_slots:
                raise HomeAssistantError(
                    "Tariff schedule writes are only supported for DJI Power 2000"
                )

            # Use a recent device report for the full-table difference check.
            # Tariff writes replace the complete table and never merge periods.
            cfg = self.state.config
            if not snapshot_is_fresh(
                last_report_monotonic=self._last_config_report_monotonic,
                now_monotonic=asyncio.get_running_loop().time(),
                max_age_s=CONFIG_CACHE_MAX_AGE_SECONDS,
            ):
                cfg = await self._read_current_config()
                self._apply_config(cfg, source="0x60_tariff_prewrite", notify=False)

            if self._skip_unchanged_config_write(
                0x1016,
                cfg is not None and tariff_schedule_signature(cfg.tariff_slots)
                == tariff_schedule_signature(updated_slots),
            ):
                return

            payload, updated_slots = build_0x63_tariff_schedule_payload(updated_slots)
            await self._send_0x63_and_apply(
                payload,
                expected_tlv=0x1016,
                verification_key=(
                    f"tariff_schedule_{preset}" if preset else "tariff_schedule"
                ),
                expected_tariff_slots=updated_slots,
                updated_tariff_slots=updated_slots,
            )

    async def async_set_all_day_tariff(self, kind: str) -> None:
        """Compatibility wrapper for the two legacy preset buttons."""
        preset = {
            "peak": "all_day_peak",
            "off_peak": "all_day_off_peak",
        }.get(kind)
        if preset is None:
            raise HomeAssistantError(f"Unsupported tariff preset: {kind}")
        await self.async_set_tariff_schedule(preset=preset)

    async def async_start_payload_capture(
        self,
        *,
        duration_seconds: int = DEFAULT_CAPTURE_DURATION_SECONDS,
        max_frames: int = DEFAULT_CAPTURE_MAX_FRAMES,
    ) -> None:
        """Capture a bounded set of safe protocol payloads in memory.

        Authentication command 0x6A is never retained. Captured data is exposed
        only through Home Assistant diagnostics; no continuous file writer is used.
        """
        duration = max(1, min(300, int(duration_seconds)))
        self._capture_max_frames = max(1, min(1000, int(max_frames)))
        self._capture_frames = deque(maxlen=self._capture_max_frames)
        self._capture_started_at = utcnow_iso()
        self._capture_finished_at = None
        self._capture_active_until_monotonic = (
            asyncio.get_running_loop().time() + duration
        )
        self._notify_listeners()

    @property
    def device_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, self.address)},
            "name": self.device_name,
            "manufacturer": "DJI",
            "model": self.model,
            "connections": {(dr.CONNECTION_BLUETOOTH, self.address)},
        }
        if self.state.config and self.state.config.firmware:
            info["sw_version"] = self.state.config.firmware
        return info
