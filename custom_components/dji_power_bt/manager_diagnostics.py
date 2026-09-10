"""Diagnostic snapshots for the split DJI Power manager.

This is the only module outside the manager mixins that intentionally reads
manager-private runtime fields. Home Assistant's diagnostics platform consumes
these stable snapshots instead of coupling itself to implementation details.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .manager_constants import (
    CONFIG_CACHE_MAX_AGE_SECONDS,
    GATT_WRITE_TIMEOUT,
    NOTIFY_WATCHDOG_TIMEOUT,
    OUTPUT_TABLE_CACHE_MAX_AGE_SECONDS,
)
from .write_policy import ACTIVE_WRITE_VERIFICATION, OFF_PEAK_POWER_WRITE_VERIFICATION


def manager_runtime_snapshot(manager: Any) -> dict[str, Any]:
    """Return one manager's unredacted bounded runtime snapshot."""
    state = manager.state
    cfg = state.config
    return {
        "connected": state.connected,
        "ble_enabled": state.ble_enabled,
        "authenticated": state.authenticated,
        "model": manager.model,
        "model_code": f"0x{manager.model_code:02X}" if manager.model_code is not None else None,
        "last_error": state.last_error,
        "last_notify_at": state.last_notify_at,
        "last_0x61_at": state.last_0x61_at,
        "last_0x62_at": state.last_0x62_at,
        "last_0x66_at": state.last_0x66_at,
        "last_0x60_refresh_at": state.last_0x60_refresh_at,
        "last_write_result": state.last_write_result,
        "last_write_ack_at": state.last_write_ack_at,
        "last_write_sequence": state.last_write_sequence,
        "last_write_property": state.last_write_property,
        "reflection_confirmed": state.reflection_confirmed,
        "reflection_source": state.reflection_source,
        "write_verification_pending": state.write_verification_pending,
        # Precise connection semantics introduced in v0.7.30.
        "last_gatt_connect_at": state.last_gatt_connect_at,
        "last_ready_at": state.last_ready_at,
        "gatt_connect_count": state.gatt_connect_count,
        "gatt_reconnect_count": state.gatt_reconnect_count,
        "successful_reconnect_count": state.successful_reconnect_count,
        "connection_counters": {
            "scope": "manager_runtime_since_setup",
            "gatt_connect_count": state.gatt_connect_count,
            "gatt_reconnect_count": state.gatt_reconnect_count,
            "successful_reconnect_count": state.successful_reconnect_count,
        },
        # Compatibility aliases retained for existing diagnostic consumers.
        "last_connect_at": state.last_connect_at,
        "reconnect_count": state.reconnect_count,
        "last_disconnect_reason": state.last_disconnect_reason,
        "last_disconnect_at": state.last_disconnect_at,
        "last_connection_error": state.last_connection_error,
        "last_connection_error_at": state.last_connection_error_at,
        "last_connection_failure_category": state.last_connection_failure_category,
        "last_connection_failure_phase": state.last_connection_failure_phase,
        "connection_phase": state.connection_phase,
        "bluetooth_source": state.bluetooth_source,
        "runtime_tuning": {
            "notify_watchdog_timeout_s": NOTIFY_WATCHDOG_TIMEOUT,
            "gatt_write_timeout_s": GATT_WRITE_TIMEOUT,
            "config_cache_max_age_s": CONFIG_CACHE_MAX_AGE_SECONDS,
            "output_table_cache_max_age_s": OUTPUT_TABLE_CACHE_MAX_AGE_SECONDS,
            "active_verification_wait_for_report_s": ACTIVE_WRITE_VERIFICATION.wait_for_report_s,
            "off_peak_power_passive_wait_s": OFF_PEAK_POWER_WRITE_VERIFICATION.wait_for_report_s,
        },
        # Legacy flat timeout keys retained for comparison with older diagnostics.
        "notify_watchdog_timeout_s": NOTIFY_WATCHDOG_TIMEOUT,
        "gatt_write_timeout_s": GATT_WRITE_TIMEOUT,
        "gatt_write_timeout_count": state.gatt_write_timeout_count,
        "last_gatt_write_timeout_at": state.last_gatt_write_timeout_at,
        "write_lock_age_s": manager.write_lock_age_s,
        "write_lock_context": manager._write_lock_context,
        "pending_0x62_ack_task_count": manager.ack_task_count,
        "stale_connection_cleanup_count": state.stale_connection_cleanup_count,
        "last_stale_connection_cleanup_at": state.last_stale_connection_cleanup_at,
        "telemetry_update_interval_s": manager.telemetry_update_interval,
        "telemetry_publish_pending": manager._telemetry_publish_pending,
        "pending_request_count": len(manager._pending),
        "connection_generation": manager._connection_generation,
        "pending_verification_count": len(manager._pending_verifications),
        "ble_traffic_control": {
            "config_read_request_count": state.config_read_request_count,
            "config_cache_hit_count": state.config_cache_hit_count,
            "verification_readback_count": state.verification_readback_count,
            "passive_verification_timeout_count": state.passive_verification_timeout_count,
            "config_cache_max_age_s": CONFIG_CACHE_MAX_AGE_SECONDS,
            "output_table_cache_max_age_s": OUTPUT_TABLE_CACHE_MAX_AGE_SECONDS,
            "active_verification_wait_for_report_s": ACTIVE_WRITE_VERIFICATION.wait_for_report_s,
            "off_peak_power_passive_wait_s": OFF_PEAK_POWER_WRITE_VERIFICATION.wait_for_report_s,
        },
        "write_history": manager.write_history,
        "gatt_frame_reassembly": manager.reassembly_diagnostics,
        "capabilities": asdict(manager.capabilities),
        "off_peak_charging_power_step": {
            "configured_w": manager.capabilities.off_peak_charging_power_step_w,
            "source": "model_profile" if manager.capabilities.off_peak_charging_power_step_w is not None else None,
            "reported_0x1018_offset_34_candidate_w": (
                cfg.unknown_0x1018_step_candidate_w if cfg else None
            ),
            "candidate_matches_configured": (
                cfg is not None
                and manager.capabilities.off_peak_charging_power_step_w is not None
                and cfg.unknown_0x1018_step_candidate_w
                == manager.capabilities.off_peak_charging_power_step_w
            ),
        },
        "consecutive_connect_failures": state.consecutive_connect_failures,
        "last_retry_delay_s": state.last_retry_delay_s,
        "last_device_resolution": state.last_device_resolution,
        "connector_name": state.connector_name,
        "configured_address": manager.address,
        "resolved_ble_address": state.resolved_ble_address,
        "resolved_ble_name": state.resolved_ble_name,
        "advertised_name": state.advertised_name,
        "advertisement_source": state.advertisement_source,
        "advertised_model": state.advertised_model,
        "advertised_model_code": (
            f"0x{state.advertised_model_code:02X}"
            if state.advertised_model_code is not None
            else None
        ),
        "advertised_bound": state.advertised_bound,
        "advertised_mac_candidate": state.advertised_mac_candidate,
        "manufacturer_ids": [f"0x{value:04X}" for value in state.manufacturer_ids],
        "identity_status": state.identity_status,
        "firmware": cfg.firmware if cfg else None,
        "communication_module_firmware": cfg.communication_module_firmware if cfg else None,
        "communication_module_firmware_dji_home_label": "Dongle version",
        "timezone_offset_min": cfg.timezone_offset_min if cfg else None,
        "metrics": state.metrics.as_dict(),
        "config": cfg.as_dict() if cfg else None,
        "latest_safe_payloads": manager.latest_payloads,
        "hms_0x66": manager.hms_diagnostics,
        "payload_capture": manager.payload_capture_info,
        "captured_safe_payloads": manager.captured_payloads,
        "client_lifecycle": manager.client_lifecycle_diagnostics,
        "connection_event_history_limit": getattr(manager._local_connection_event_history, "maxlen", None),
        "connection_event_history": manager.connection_event_history,
    }


def domain_connection_runtime_snapshot(manager: Any) -> dict[str, Any] | None:
    """Return the shared per-domain connection state without redaction."""
    runtime = getattr(manager, "_domain_runtime", None)
    if runtime is None:
        return None
    manager_summaries = []
    for entry_id, item in getattr(runtime, "managers", {}).items():
        lifecycle = item.client_lifecycle_diagnostics
        manager_summaries.append(
            {
                "entry_id": entry_id,
                "model": item.model,
                "address": item.address,
                "connected": item.state.connected,
                "authenticated": item.state.authenticated,
                "connection_phase": item.state.connection_phase,
                "active_client_present": lifecycle["active_client_present"],
                "active_client_is_connected": lifecycle["active_client_is_connected"],
                "retired_client_present": lifecycle["retired_client_present"],
                "retired_client_is_connected": lifecycle["retired_client_is_connected"],
                "fresh_advertisement_required": lifecycle["fresh_advertisement_required"],
            }
        )
    return {
        "connection_lock_holder": getattr(runtime, "connection_lock_holder", None),
        "connection_lock_waiters": getattr(runtime, "connection_lock_waiters", 0),
        "manager_count": len(manager_summaries),
        "managers": manager_summaries,
        "connection_event_history_limit": getattr(
            getattr(runtime, "connection_event_history", None), "maxlen", None
        ),
        "connection_event_history": list(getattr(runtime, "connection_event_history", ())),
    }
