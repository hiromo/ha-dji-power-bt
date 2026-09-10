from __future__ import annotations

import json
from pathlib import Path

from custom_components.dji_power_bt import protocol

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dji_power_bt"


def _sources(*names: str) -> str:
    return "\n".join((COMPONENT / name).read_text() for name in names)


def test_release_version_is_0_7_31_and_public_config_entry_baseline_is_1() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    config_flow = (COMPONENT / "config_flow.py").read_text()
    setup = (COMPONENT / "__init__.py").read_text()
    entity = (COMPONENT / "entity.py").read_text()

    assert manifest["version"] == "0.7.31"
    assert "VERSION = 1" in config_flow
    assert "async_migrate_entry" not in setup
    assert (
        'self._attr_unique_id = f"{manager.address}_{key}".replace(":", "_").lower()'
        in entity
    )


def test_manager_and_protocol_are_split_behind_compatibility_facades() -> None:
    manager = (COMPONENT / "manager.py").read_text()
    protocol_facade = (COMPONENT / "protocol.py").read_text()
    for name in (
        "manager_connection.py",
        "manager_payload.py",
        "manager_transport.py",
        "manager_types.py",
        "manager_diagnostics.py",
        "protocol_frame.py",
        "protocol_hms.py",
        "protocol_config.py",
        "protocol_realtime.py",
    ):
        assert (COMPONENT / name).exists()
    assert "ManagerConnectionMixin" in manager
    assert "ManagerTransportMixin" in manager
    assert "Compatibility facade" in protocol_facade
    assert hasattr(protocol, "parse_realtime_metrics")
    assert hasattr(protocol, "parse_power_config")


def test_connection_constants_have_one_shared_source_of_truth() -> None:
    source = (COMPONENT / "manager_constants.py").read_text()
    assert "UNEXPECTED_DISCONNECT_SETTLE_SECONDS = 5.0" in source
    assert "FRESH_ADVERTISEMENT_TIMEOUT_SECONDS = 60.0" in source
    assert "ESTABLISH_CONNECTION_MAX_ATTEMPTS = 2" in source
    assert "RECONNECT_BACKOFF_SECONDS = (10.0, 30.0, 60.0, 120.0, 300.0)" in source


def test_expected_disconnect_bookkeeping_remains_weak_reference_based() -> None:
    manager = (COMPONENT / "manager.py").read_text()
    connection = (COMPONENT / "manager_connection.py").read_text()
    constants = (COMPONENT / "manager_constants.py").read_text()
    assert "weakref.ReferenceType[BleakClient]" in manager
    assert "weakref.ref(client)" in connection
    assert "expected_client = expected_record[0]()" in connection
    assert "EXPECTED_DISCONNECT_RECORD_TTL_SECONDS = 300.0" in constants
    assert "expect_callback = self._retired_client is not client" in connection


def test_connection_diagnostic_semantics_are_explicit_and_legacy_aliases_remain() -> None:
    types_source = (COMPONENT / "manager_types.py").read_text()
    diag_source = (COMPONENT / "manager_diagnostics.py").read_text()
    for name in (
        "last_gatt_connect_at",
        "last_ready_at",
        "gatt_connect_count",
        "gatt_reconnect_count",
        "successful_reconnect_count",
    ):
        assert name in types_source
        assert f'"{name}"' in diag_source
    assert "def last_connect_at" in types_source
    assert "def reconnect_count" in types_source


def test_hms_fast_path_reuses_structural_parse() -> None:
    payload_source = (COMPONENT / "manager_payload.py").read_text()
    hms_source = (COMPONENT / "protocol_hms.py").read_text()
    assert "self._last_hms_body == body" in payload_source
    assert "self._hms_fast_path_hit_count += 1" in payload_source
    assert "self._hms_full_parse_count += 1" in payload_source
    assert "split_0x66_hms_payload" in hms_source
    assert "reuse_0x66_hms_report" in hms_source


def test_xt60_support_is_preserved_after_protocol_split() -> None:
    realtime = (COMPONENT / "protocol_realtime.py").read_text()
    sensor = (COMPONENT / "sensor.py").read_text()
    capabilities = (COMPONENT / "capabilities.py").read_text()
    assert "xt60_input_power_w" in realtime
    assert "xt60_output_power_w" in realtime
    assert '"xt60_input_power"' in sensor
    assert '"xt60_output_power"' in sensor
    assert "has_xt60_accessory" in capabilities
