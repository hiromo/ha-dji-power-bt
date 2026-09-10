from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.dji_power_bt import protocol

# Stable public/behavioral contracts consolidated from historical release tests.
ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dji_power_bt"


def _sources(*names: str) -> str:
    return "\n".join((COMPONENT / name).read_text() for name in names)


def _manager_impl_source() -> str:
    return _sources(
        "manager.py", "manager_types.py", "manager_connection.py",
        "manager_payload.py", "manager_transport.py", "manager_constants.py",
    )


def _protocol_impl_source() -> str:
    return _sources(
        "protocol.py", "protocol_common.py", "protocol_discovery.py",
        "protocol_frame.py", "protocol_hms.py", "protocol_config.py",
        "protocol_realtime.py",
    )


def test_tariff_button_icons_are_rate_semantic() -> None:
    source = (COMPONENT / "button.py").read_text()
    peak_start = source.index('"set_all_day_peak_tariff"')
    off_peak_start = source.index('"set_all_day_off_peak_tariff"')
    peak_block = source[peak_start:off_peak_start]
    off_peak_block = source[off_peak_start:]
    assert '"mdi:weather-night"' in peak_block
    assert '"mdi:weather-sunny-alert"' in off_peak_block


def test_tariff_profile_entity_is_removed_and_match_is_schedule_attribute() -> None:
    source = (COMPONENT / "sensor.py").read_text()
    assert "DjiPowerTariffScheduleProfileSensor" not in source
    assert '"tariff_schedule_profile"' not in source
    assert '"preset_match"' in source
    assert "classify_tariff_schedule(m.state.config.tariff_slots)" in source

    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ja.json",
    ):
        data = json.loads(path.read_text())
        assert "tariff_schedule_profile" not in data["entity"]["sensor"]


def test_core_bluetooth_requirement_is_not_redeclared() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())

    assert "bluetooth" in manifest["dependencies"]
    assert "bluetooth_adapters" in manifest["dependencies"]
    assert "requirements" not in manifest


def test_hacs_custom_repository_metadata_is_complete() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs == {"name": "DJI Power Bluetooth"}
    assert manifest["documentation"] == (
        "https://github.com/hiromo/ha-dji-power-bt"
    )
    assert manifest["issue_tracker"] == (
        "https://github.com/hiromo/ha-dji-power-bt/issues"
    )
    assert manifest["codeowners"] == ["@hiromo"]
    assert [path.name for path in (ROOT / "custom_components").iterdir()] == [
        "dji_power_bt"
    ]


def test_public_documentation_is_english_and_user_focused() -> None:
    markdown_files = [
        path
        for path in ROOT.rglob("*.md")
        if ".git" not in path.parts
        and ".pytest_cache" not in path.parts
        and "automations" not in path.parts
    ]
    cjk_text = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
    non_english = [
        str(path.relative_to(ROOT))
        for path in markdown_files
        if cjk_text.search(path.read_text())
    ]

    assert non_english == []

    readme = (ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split())
    changelog = (ROOT / "CHANGELOG.md").read_text()
    required_readme_contracts = (
        "one persistent BLE GATT connection",
        "telemetry approximately once per second",
        "one connection slot",
        "Simultaneous persistent connections to multiple DJI Power stations",
        "Private development began in early June 2026",
        "DJI Power 2000",
        "DJI Power 1000 Mini",
        "Grid-Tied ESS is not supported",
        "SoC <= Discharge limit + 5%",
        "Off-peak charging power",
        "Set all-day off-peak tariff",
        "Set all-day peak tariff",
        "Both entities are disabled by default",
        "completely replaces",
        "dji_power_bt.set_scheduled_energy_settings",
        "separate `0x1016/0x1017` records",
        "10, 30, 60, 120, and 300 seconds",
        "Power 1000 Mini charging mode",
        "/config/.storage/core.config_entries",
        "capturing and analyzing the BLE authentication exchange",
        "DJI Home access over Wi-Fi or the DJI cloud does not occupy",
        "Apache License 2.0",
    )
    for contract in required_readme_contracts:
        assert contract in normalized_readme

    assert "## v0." not in readme
    assert "Close DJI Home completely" not in readme
    assert "A station connected to DJI Home is unavailable" not in readme
    assert "docs/release-history.md" in readme
    assert "## Unreleased" in changelog

    license_text = (ROOT / "LICENSE").read_text()
    assert license_text.startswith("Apache License")
    assert "Version 2.0, January 2004" in license_text


def test_integration_identity_is_dji_power_bt() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    setup_source = (COMPONENT / "__init__.py").read_text()
    strings = json.loads((COMPONENT / "strings.json").read_text())
    en = json.loads((COMPONENT / "translations" / "en.json").read_text())
    ja = json.loads((COMPONENT / "translations" / "ja.json").read_text())
    services = (COMPONENT / "services.yaml").read_text()

    assert COMPONENT.name == "dji_power_bt"
    assert not (ROOT / "custom_components" / "dji_power").exists()
    assert manifest["domain"] == "dji_power_bt"
    assert manifest["name"] == "DJI Power Bluetooth"
    assert "CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)" in setup_source
    assert "integration: dji_power_bt" in services
    assert strings["title"] == "DJI Power Bluetooth"
    assert en["title"] == "DJI Power Bluetooth"
    assert ja["title"] == "DJI Power Bluetooth"
    assert strings["config"]["step"]["reauth_confirm"]["title"] == (
        "Re-authenticate DJI Power Bluetooth"
    )
    assert en["config"]["step"]["reauth_confirm"]["title"] == (
        "Re-authenticate DJI Power Bluetooth"
    )
    assert strings["options"]["step"]["init"]["title"] == (
        "DJI Power Bluetooth options"
    )
    assert en["options"]["step"]["init"]["title"] == (
        "DJI Power Bluetooth options"
    )
    assert ja["config"]["step"]["reauth_confirm"]["title"] == (
        "DJI Power Bluetooth の再認証"
    )
    assert ja["options"]["step"]["init"]["title"] == (
        "DJI Power Bluetooth オプション"
    )


def test_authentication_forms_allow_method_reselection() -> None:
    source = (COMPONENT / "config_flow.py").read_text()
    helper = source.split(
        "def _change_auth_method_requested", 1
    )[1].split("async def _async_create_device_entry", 1)[0]

    assert "_async_claim_user_selected_device" not in source
    assert source.count("self._change_auth_method_requested(user_input)") == 6
    assert source.count("CONF_CHANGE_AUTH_METHOD, default=False") == 6
    assert source.count("BooleanSelector()") == 6
    for attribute in (
        "_cloud_client",
        "_cloud_devices",
        "_member_token",
        "_email",
        "_password",
        "_captcha_request_id",
        "_captcha_ticket",
    ):
        assert f"self.{attribute} = None" in helper

    setup_steps = (
        "manual",
        "token",
        "account",
        "captcha",
        "two_factor",
        "cloud_device",
    )
    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ja.json",
    ):
        data = json.loads(path.read_text())
        for step in setup_steps:
            assert "change_auth_method" in data["config"]["step"][step]["data"]
        assert "required" in data["config"]["error"]


def test_bulk_0x1018_service_is_declared_and_translated() -> None:
    services = (COMPONENT / "services.yaml").read_text()
    assert "set_scheduled_energy_settings:" in services
    for field in (
        "device_id:",
        "energy_optimization_mode:",
        "peak_discharging:",
        "off_peak_charging:",
        "off_peak_charging_power:",
    ):
        assert field in services

    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ja.json",
    ):
        data = json.loads(path.read_text())
        assert "set_scheduled_energy_settings" in data["services"]


def test_bulk_service_registration_and_manager_method_are_present() -> None:
    setup_source = (COMPONENT / "__init__.py").read_text()
    manager_source = _manager_impl_source()
    assert "SERVICE_SET_SCHEDULED_ENERGY_SETTINGS" in setup_source
    assert "_SERVICE_SCHEDULED_ENERGY_SCHEMA" in setup_source
    assert "async_set_scheduled_energy_settings" in setup_source
    assert "async def async_set_scheduled_energy_settings(" in manager_source
    assert 'verification_key="scheduled_energy_settings"' in manager_source


def test_tariff_schedule_action_is_declared_registered_and_translated() -> None:
    services = (COMPONENT / "services.yaml").read_text()
    setup_source = (COMPONENT / "__init__.py").read_text()
    manager_source = _manager_impl_source()
    button_source = (COMPONENT / "button.py").read_text()

    assert "set_tariff_schedule:" in services
    for field in ("device_id:", "preset:", "periods:"):
        assert field in services
    for translation_key in ("tariff_preset", "tariff_kind", "tariff_weekday"):
        assert f"translation_key: {translation_key}" in services
    assert "SERVICE_SET_TARIFF_SCHEDULE" in setup_source
    assert "_SERVICE_TARIFF_SCHEDULE_SCHEMA" in setup_source
    assert "async def async_set_tariff_schedule(" in manager_source
    assert "expected_tariff_slots=updated_slots" in manager_source
    assert 'preset="all_day_peak"' in button_source
    assert 'preset="all_day_off_peak"' in button_source

    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ja.json",
    ):
        data = json.loads(path.read_text())
        assert "set_tariff_schedule" in data["services"]
        assert {"tariff_preset", "tariff_kind", "tariff_weekday"}.issubset(
            data["selector"]
        )


def test_surplus_automation_v7_7c_preserves_v7_5c_and_uses_current_period() -> None:
    source = (
        ROOT / "automations" / "power2000_surplus_absorption_v7_7c.yaml"
    ).read_text()

    assert "self_consumption_min_surplus_charge_ratio: 0.5" in source
    assert "self_consumption_sub_min_charge_allowed:" in source
    assert "and not self_consumption_sub_min_charge_allowed" in source
    assert "and (self_consumption_sub_min_charge_allowed" in source
    assert "action: dji_power_bt.set_tariff_schedule" in source
    assert "action: dji_power_bt.set_scheduled_energy_settings" in source
    assert "sensor.dji_power_2000_tariff_period" in source
    assert "sensor.dji_power_2000_tariff_time_slots" not in source
    assert "preset_match" not in source
    assert "tariff_schedule_profile" not in source
    assert "button.dji_power_2000_set_all_day" not in source


def test_ac_inlet_outlet_entities_supersede_grid_port_entities() -> None:
    sensor_source = (COMPONENT / "sensor.py").read_text()
    protocol_source = _protocol_impl_source()

    assert '"ac_input_power"' in sensor_source
    assert '"ac_output_power"' in sensor_source
    assert '"grid_port_input_power"' not in sensor_source
    assert '"grid_port_output_power"' not in sensor_source
    assert '"charging_input_power"' not in sensor_source
    for key in (
        "ac_inlet_input_power_w",
        "ac_inlet_output_power_w",
        "ac_outlet_input_power_w",
        "ac_outlet_output_power_w",
    ):
        assert key in protocol_source
    assert "grid_port_input_power_w" not in protocol_source
    assert "grid_port_output_power_w" not in protocol_source
    assert '1: "ac_inlet"' in protocol_source
    assert '2: "ac_outlet"' in protocol_source


def test_active_off_peak_identifiers_are_consistent() -> None:
    services = (COMPONENT / "services.yaml").read_text()
    assert "off_peak_charging:" in services
    assert "off_peak_charging_power:" in services
    assert "offpeak_charging:" not in services
    assert "offpeak_charging_power:" not in services

    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ja.json",
    ):
        text = path.read_text()
        assert "all_day_off_peak" in text
        assert "all_day_offpeak" not in text
        assert '"offpeak_charging"' not in text
        assert '"offpeak_charging_power"' not in text

    assert "all_day_off_peak" in services


def test_tariff_period_off_peak_state_has_hyphenated_display() -> None:
    sensor_source = (COMPONENT / "sensor.py").read_text()
    assert '_attr_options = ["disabled", "peak", "off_peak", "none", "unknown"]' in sensor_source
    assert '_attr_translation_key = "tariff_period"' in sensor_source

    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ja.json",
    ):
        data = json.loads(path.read_text())
        states = data["entity"]["sensor"]["tariff_period"]["state"]
        assert states["off_peak"] == "Off-peak"


def test_operation_state_is_removed_but_objective_power_delta_remains() -> None:
    sensor_source = (COMPONENT / "sensor.py").read_text()
    protocol_source = _protocol_impl_source()
    manager_source = _manager_impl_source()

    assert 'key="operation_state"' not in sensor_source
    assert "operation_state" not in protocol_source
    assert "operation_state" not in manager_source
    assert '"input_minus_output_w"' in protocol_source


def test_refresh_config_button_and_manual_refresh_path_are_removed() -> None:
    button_source = (COMPONENT / "button.py").read_text()
    manager_source = _manager_impl_source()

    assert '"refresh_config"' not in button_source
    assert "_refresh_config" not in button_source
    assert "async_refresh_config" not in manager_source
    assert "0x60_manual" not in manager_source


def test_protocol_docs_record_0x1018_edit_and_preserve_ranges() -> None:
    commands_doc = (ROOT / "docs" / "protocol" / "commands.md").read_text()
    assert "0x00" in commands_doc
    assert "0x01" in commands_doc
    assert "0x02" in commands_doc
    assert "0x03" in commands_doc
    assert "0x0C–0x0F" in commands_doc
    assert "0x10–0x55" in commands_doc
    assert "read-modify-write" in commands_doc


def test_public_ac_entities_use_verified_inlet_and_outlet_directions() -> None:
    sensor_source = (COMPONENT / "sensor.py").read_text()
    manager_source = _manager_impl_source()

    assert '"ac_input_power"' in sensor_source
    assert '"AC input power"' in sensor_source
    assert 'lambda m: m.state.ac_input_power_w' in sensor_source
    assert '"ac_output_power"' in sensor_source
    assert 'lambda m: m.state.ac_output_power_w' in sensor_source
    assert '"grid_port_input_power"' not in sensor_source
    assert '"grid_port_output_power"' not in sensor_source
    assert "return self.metrics.ac_inlet_input_power_w" in manager_source
    assert "return self.metrics.ac_outlet_output_power_w" in manager_source


def test_reverse_ac_directions_are_diagnostics_only() -> None:
    sensor_source = (COMPONENT / "sensor.py").read_text()
    protocol_source = _protocol_impl_source()

    assert "ac_inlet_output_power_w" in protocol_source
    assert "ac_outlet_input_power_w" in protocol_source
    assert '"ac_inlet_output_power"' not in sensor_source
    assert '"ac_outlet_input_power"' not in sensor_source


def test_dji_home_ac_and_sdc_input_sample_maps_exactly() -> None:
    # DJI Home at 2026-08-05 13:20:13 JST displayed:
    # Total input 1515 W = AC 1478 W + SDC 37 W.
    payload = bytes.fromhex(
        "01 00 10 00 7a 7c 26 d0 9f 01 00 00 00 00 00 00 "
        "40 30 09 00 07 00 30 35 30 30 31 62 00 "
        "10 30 26 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "20 30 0c 00 1c 25 08 00 01 1c 25 00 00 be 0f 01 "
        "30 30 85 00 e4 02 eb 05 31 30 7d 00 "
        "32 30 19 00 01 33 30 14 00 34 30 10 00 "
        "01 01 00 00 00 c6 05 00 38 30 00 00 35 30 00 00 "
        "32 30 19 00 02 33 30 14 00 34 30 10 00 "
        "01 02 00 e4 02 00 00 00 38 30 00 00 35 30 00 00 "
        "32 30 3f 00 04 33 30 3a 00 34 30 36 00 "
        "01 05 00 00 00 25 00 00 38 30 26 00 "
        # Original 14-byte identifier replaced with ASCII "TESTDEVICE0001".
        "54 45 53 54 44 45 56 49 43 45 30 30 30 31 00 00 02 "
        "39 30 11 00 3a 30 0d 00 01 00 00 25 00 00 00 00 00 40 06 00 00 "
        "35 30 00 00 50 30 07 00 02 01 02 02 00 00 00"
    )

    metrics = protocol.parse_realtime_metrics(payload)

    assert metrics.input_power_w == 1515
    assert metrics.ac_inlet_input_power_w == 1478
    assert metrics.sdc_input_power_w == 37
    assert metrics.ac_inlet_input_power_w + metrics.sdc_input_power_w == metrics.input_power_w
    assert metrics.ac_outlet_output_power_w == 740
    assert metrics.ac_inlet_output_power_w == 0
    assert metrics.ac_outlet_input_power_w == 0
    assert metrics.group_input_power_w == {
        "ac_inlet": 1478,
        "ac_outlet": 0,
        "sdc": 37,
    }
    assert metrics.raw_records[0]["group_name"] == "ac_inlet"
    assert metrics.raw_records[1]["group_name"] == "ac_outlet"
    assert metrics.raw_records[2]["group_name"] == "sdc"


def test_unexpected_disconnect_requires_fresh_advertisement() -> None:
    source = _manager_impl_source()
    assert "UNEXPECTED_DISCONNECT_SETTLE_SECONDS = 5.0" in source
    assert "FRESH_ADVERTISEMENT_TIMEOUT_SECONDS = 60.0" in source
    assert "async_clear_advertisement_history" in source
    assert "async_process_advertisements" in source
    assert 'resolution="fresh_after_disconnect"' in source
    assert "Fresh advertisement is required before reconnecting" in source
    assert "self._last_ble_device = None" in source


def test_connection_attempts_are_reduced_and_outer_backoff_remains() -> None:
    source = _manager_impl_source()
    assert "ESTABLISH_CONNECTION_MAX_ATTEMPTS = 2" in source
    assert "max_attempts=ESTABLISH_CONNECTION_MAX_ATTEMPTS" in source
    assert "RECONNECT_BACKOFF_SECONDS" in source


def test_cross_device_connection_history_is_in_runtime_and_diagnostics() -> None:
    runtime_source = (COMPONENT / "runtime.py").read_text()
    diagnostics_source = (COMPONENT / "diagnostics.py").read_text()
    manager_source = _manager_impl_source()

    assert "connection_event_history" in runtime_source
    assert "next_connection_attempt_id" in runtime_source
    assert "connection_lock_holder" in runtime_source
    assert "connection_lock_waiters" in runtime_source
    assert '"domain_connection_runtime"' in diagnostics_source
    manager_diag_source = (COMPONENT / "manager_diagnostics.py").read_text()
    assert '"client_lifecycle"' in manager_diag_source
    assert '"connection_event_history"' in manager_diag_source
    assert '"unexpected_disconnect_reconnect_gate_armed"' in manager_source
    assert '"fresh_advertisement_received"' in manager_source


def test_setup_passes_shared_domain_runtime_to_each_manager() -> None:
    source = (COMPONENT / "__init__.py").read_text()
    assert "domain_runtime=runtime" in source


def _tlv(tlv_id: int, value: bytes) -> bytes:
    return tlv_id.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def _firmware_value(station: str, dongle: str) -> bytes:
    value = bytearray(53)
    value[7:23] = station.encode("ascii").ljust(16, b"\x00")
    value[24:40] = dongle.encode("ascii").ljust(16, b"\x00")
    return bytes(value)


def test_power_2000_and_power_1000_mini_share_firmware_tlv_layout() -> None:
    power_2000 = protocol.parse_power_config(
        _tlv(0x1000, _firmware_value("01.00.1500", "03.03.0000")),
        source_cmd_id=0x60,
    )
    power_1000_mini = protocol.parse_power_config(
        _tlv(0x1000, _firmware_value("01.00.0300", "03.03.0000")),
        source_cmd_id=0x60,
    )

    assert power_2000.firmware == "01.00.1500"
    assert power_2000.communication_module_firmware == "03.03.0000"
    assert power_1000_mini.firmware == "01.00.0300"
    assert power_1000_mini.communication_module_firmware == "03.03.0000"


def test_device_registry_firmware_is_synchronized_without_model_gate() -> None:
    manager_source = _sources("manager.py", "manager_transport.py")
    transport_source = (COMPONENT / "manager_transport.py").read_text()
    sensor_source = (COMPONENT / "sensor.py").read_text()

    assert "self._sync_device_registry_firmware()" in transport_source
    assert "identifiers={(DOMAIN, self.address)}" in transport_source
    assert "registry.async_update_device(device.id, sw_version=firmware)" in transport_source

    sync_block = transport_source.split(
        "def _sync_device_registry_firmware", 1
    )[1].split("async def _write_frame", 1)[0]
    assert "model_code" not in sync_block
    assert "capabilities" not in sync_block

    firmware_block = sensor_source.split('key="firmware"', 1)[1][:500]
    module_block = sensor_source.split('key="communication_module_firmware"', 1)[1][:700]
    assert "supported_fn=" not in firmware_block
    assert "supported_fn=" not in module_block


def test_unexpected_disconnect_age_diagnostic_has_explicit_last_prefix() -> None:
    manager_source = _manager_impl_source()

    assert '"last_unexpected_disconnect_age_s": disconnect_age' in manager_source
    assert '"unexpected_disconnect_age_s": disconnect_age' not in manager_source


def test_v0_7_9_does_not_remove_xt60_support() -> None:
    protocol_source = _protocol_impl_source()
    sensor_source = (COMPONENT / "sensor.py").read_text()
    capabilities_source = (COMPONENT / "capabilities.py").read_text()

    assert "xt60_input_power_w" in protocol_source
    assert "xt60_output_power_w" in protocol_source
    assert '"xt60_input_power"' in sensor_source
    assert '"xt60_output_power"' in sensor_source
    assert "has_xt60_accessory" in capabilities_source
