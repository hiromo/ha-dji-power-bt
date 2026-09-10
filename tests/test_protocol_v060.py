from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "dji_power_bt"

pkg = types.ModuleType("custom_components")
pkg.__path__ = []
sys.modules.setdefault("custom_components", pkg)
subpkg = types.ModuleType("custom_components.dji_power_bt")
subpkg.__path__ = [str(ROOT)]
sys.modules.setdefault("custom_components.dji_power_bt", subpkg)


def load(name: str):
    fq = f"custom_components.dji_power_bt.{name}"
    if fq in sys.modules:
        return sys.modules[fq]
    spec = importlib.util.spec_from_file_location(fq, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fq] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


const = load("const")
protocol = load("protocol")
capabilities = load("capabilities")


def tlv(tlv_id: int, value: bytes) -> bytes:
    return tlv_id.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def output_record(interface: int, port: int, state: int) -> bytes:
    return tlv(0x1014, bytes([interface, port, state]))


def charging_record(mode_id: int, power_w: int, selected: int) -> bytes:
    return tlv(
        0x101F,
        bytes([mode_id]) + power_w.to_bytes(4, "little") + bytes([selected]),
    )


def base_config_prefix() -> bytes:
    return tlv(0x100E, b"identifier")


def test_reassembler_handles_split_frames_multiple_frames_and_payload_sync_byte():
    payload_1 = b"abc\x55def"
    payload_2 = b"second"
    raw_1 = protocol.build_duml_frame(
        seq=1, cmd_set=0x5A, cmd_id=0x61, payload=payload_1
    )
    raw_2 = protocol.build_duml_frame(
        seq=2, cmd_set=0x5A, cmd_id=0x66, payload=payload_2
    )
    parser = protocol.DumlReassembler()

    assert parser.feed(raw_1[:2]) == []
    assert parser.feed(raw_1[2:9]) == []
    frames = parser.feed(raw_1[9:] + raw_2)

    assert [frame.seq for frame in frames] == [1, 2]
    assert frames[0].payload == payload_1
    assert frames[1].payload == payload_2
    assert parser.diagnostics()["frames_ok"] == 2


def test_reassembler_resynchronizes_after_noise_and_bad_header_candidate():
    raw = protocol.build_duml_frame(
        seq=3, cmd_set=0x5A, cmd_id=0x61, payload=b"ok"
    )
    parser = protocol.DumlReassembler()
    frames = parser.feed(b"noise\x55\x00\x00\x00junk" + raw)
    assert len(frames) == 1
    assert frames[0].seq == 3
    assert parser.diagnostics()["discarded_byte_count"] > 0


def test_power_1000_mini_output_table_and_full_table_write():
    value_100d = b"".join(
        (
            output_record(0x02, 1, 0x02),  # AC off
            output_record(0x04, 1, 0x01),
            output_record(0x04, 2, 0x01),
            output_record(0x03, 1, 0x01),
            output_record(0x03, 2, 0x01),
            output_record(0x05, 1, 0x01),  # SDC on
        )
    )
    cfg = protocol.parse_power_config(
        base_config_prefix() + tlv(0x100D, value_100d), source_cmd_id=0x60
    )
    assert len(cfg.output_interface_states) == 6
    assert cfg.ac_output_enabled is False
    assert cfg.sdc_enabled is True

    payload, updated = protocol.build_0x63_output_payload_from_config(
        cfg, interface_type=0x02, port_index=1, enabled=True
    )
    assert payload[:4] == b"\x00\x00\x10\x00"
    outer = protocol.find_first_tlv(payload, 0x100D, min_length=42)
    assert outer is not None
    records = protocol.find_tlvs(outer[1], 0x000D, expected_lengths={3})
    assert len(records) == 6
    assert records[0][1] == bytes([0x02, 1, 0x01])
    assert records[-1][1] == bytes([0x05, 1, 0x01])
    assert next(x for x in updated if x.interface_type == 2).enabled is True


def test_power_2000_single_output_record_uses_same_full_table_logic():
    cfg = protocol.parse_power_config(
        base_config_prefix() + tlv(0x100D, output_record(0x02, 1, 0x01)),
        source_cmd_id=0x60,
    )
    payload, _ = protocol.build_0x63_output_payload_from_config(
        cfg, interface_type=0x02, port_index=1, enabled=False
    )
    outer = protocol.find_first_tlv(payload, 0x100D, min_length=7)
    assert outer is not None
    records = protocol.find_tlvs(outer[1], 0x000D, expected_lengths={3})
    assert len(records) == 1
    assert records[0][1] == bytes([0x02, 1, 0x02])


def test_mini_charging_modes_are_a_full_table_select():
    value_101e = charging_record(1, 500, 1) + charging_record(2, 1000, 2)
    cfg = protocol.parse_power_config(
        base_config_prefix() + tlv(0x101E, value_101e), source_cmd_id=0x60
    )
    assert cfg.charging_mode == "slow"
    assert [item.nominal_power_w for item in cfg.charging_modes] == [500, 1000]

    payload, updated = protocol.build_0x63_charging_mode_payload_from_config(
        cfg, "fast"
    )
    outer = protocol.find_first_tlv(payload, 0x101E, min_length=20)
    assert outer is not None
    records = protocol.find_tlvs(outer[1], 0x001E, expected_lengths={6})
    assert len(records) == 2
    assert records[0][1][-1] == 2
    assert records[1][1][-1] == 1
    assert next(item for item in updated if item.selected).key == "fast"


def test_energy_optimization_unknown_is_preserved_but_not_decoded_as_scheduled():
    value = bytearray(0x56)
    value[1] = 0x03
    cfg = protocol.parse_power_config(tlv(0x1018, bytes(value)), source_cmd_id=0x60)
    assert cfg.energy_optimization_mode == "unsupported"
    updated = protocol.update_0x1018_energy_optimization_mode(bytes(value), "disabled")
    assert updated[1] == 1
    assert updated[2:] == bytes(value)[2:]


def test_keyed_header_is_fresh_and_well_formed():
    header = protocol.build_keyed_header(timestamp_ms=123456789)
    assert len(header) == 16
    assert header[:4] == b"\x00\x00\x10\x00"
    assert int.from_bytes(header[4:12], "little") == 123456789
    assert header[12:] == b"\x00" * 4


def test_0x63_result_parser_handles_new_properties():
    payload = protocol.build_keyed_header(timestamp_ms=1) + tlv(
        0x100D, (0).to_bytes(4, "little")
    ) + tlv(0x101E, (0).to_bytes(4, "little"))
    result = protocol.parse_0x63_write_result(payload)
    assert protocol.write_result_ok(result, 0x100D)
    assert protocol.write_result_ok(result, 0x101E)


def test_charge_limit_write_matches_mini_property_order_when_1006_is_available():
    value_1005 = b"".join(
        value.to_bytes(4, "little") for value in (100, 70, 100, 15, 0, 0)
    )
    value_1006 = bytes.fromhex("00 02 50 00")
    cfg = protocol.parse_power_config(
        tlv(0x1005, value_1005) + tlv(0x1006, value_1006),
        source_cmd_id=0x60,
    )
    updated = protocol.update_0x1005_discharge_limit(value_1005, 6)
    payload = protocol.build_0x63_1005_payload_from_config(cfg, updated)
    records = protocol.iter_tlvs(payload[16:])
    assert [item[0] for item in records] == [0x1005, 0x1006, 0x100E]
    assert records[1][2] == value_1006
    assert records[2][2] == b"\x0a\x00" + b"1800efffff"


def test_reassembler_does_not_count_valid_frame_bytes_as_discarded():
    raw = protocol.build_duml_frame(
        seq=9, cmd_set=0x5A, cmd_id=0x60, payload=b"x" * 300
    )
    parser = protocol.DumlReassembler()
    assert parser.feed(raw[:256]) == []
    frames = parser.feed(raw[256:])
    assert len(frames) == 1
    assert frames[0].seq == 9
    assert parser.diagnostics()["discarded_byte_count"] == 0


def test_mini_captured_output_write_shape_and_ack_result():
    # Values taken from the supplied Android DJI Home / Power 1000 Mini capture.
    captured_write = bytes.fromhex(
        "00 00 10 00 b7 e7 1f c0 9f 01 00 00 00 00 00 00 "
        "0d 10 2a 00 "
        "0d 00 03 00 02 01 01 "
        "0d 00 03 00 04 01 01 "
        "0d 00 03 00 04 02 01 "
        "0d 00 03 00 03 01 01 "
        "0d 00 03 00 03 02 01 "
        "0d 00 03 00 05 01 01 "
        "0e 10 0c 00 0a 00 31 38 30 30 65 66 66 66 66 66"
    )
    output_tlv = protocol.find_first_tlv(captured_write, 0x100D, min_length=42)
    assert output_tlv is not None
    read_value = b"".join(
        tlv(0x1014, value)
        for _, value in protocol.find_tlvs(
            output_tlv[1], 0x000D, expected_lengths={3}
        )
    )
    cfg = protocol.parse_power_config(tlv(0x100D, read_value), source_cmd_id=0x60)
    generated, _ = protocol.build_0x63_output_payload_from_config(
        cfg, interface_type=0x02, port_index=1, enabled=True
    )
    # The generated timestamp differs, but all property records must match.
    assert generated[16:] == captured_write[16:]

    captured_ack = bytes.fromhex(
        "00 00 10 00 08 db 1f c0 9f 01 00 00 00 00 00 00 "
        "0e 10 04 00 00 00 00 00 0d 10 04 00 00 00 00 00"
    )
    result = protocol.parse_0x63_write_result(captured_ack)
    assert protocol.write_result_ok(result, 0x100D)


def test_mini_captured_charging_mode_write_shape():
    captured_write = bytes.fromhex(
        "00 00 10 00 09 48 21 c0 9f 01 00 00 00 00 00 00 "
        "0e 10 0c 00 0a 00 31 38 30 30 65 66 66 66 66 66 "
        "1e 10 14 00 "
        "1e 00 06 00 01 f4 01 00 00 02 "
        "1e 00 06 00 02 e8 03 00 00 01"
    )
    mode_tlv = protocol.find_first_tlv(captured_write, 0x101E, min_length=20)
    assert mode_tlv is not None
    read_value = b"".join(
        tlv(0x101F, value)
        for _, value in protocol.find_tlvs(
            mode_tlv[1], 0x001E, expected_lengths={6}
        )
    )
    # Reconstruct a slow-selected read snapshot and generate fast-selected write.
    slow_records = []
    for _, value in protocol.find_tlvs(read_value, 0x101F, expected_lengths={6}):
        b = bytearray(value)
        b[5] = 1 if b[0] == 1 else 2
        slow_records.append(tlv(0x101F, bytes(b)))
    cfg = protocol.parse_power_config(
        tlv(0x101E, b"".join(slow_records)), source_cmd_id=0x60
    )
    generated, _ = protocol.build_0x63_charging_mode_payload_from_config(cfg, "fast")
    assert generated[16:] == captured_write[16:]

def test_removed_mini_auxiliary_settings_are_not_requested_or_exposed():
    request = protocol.DEFAULT_STATUS_REQUEST_PAYLOAD
    assert b"\x10\x1c" not in request
    assert b"\x10\x1d" not in request
    assert b"\x10\x21" not in request

    payload = (
        tlv(0x101C, b"\x01\x01")
        + tlv(0x101D, b"\x01\x02")
        + tlv(0x1021, b"\x01\x01\x05")
    )
    cfg = protocol.parse_power_config(payload, source_cmd_id=0x60)
    data = cfg.as_dict()
    assert "ac_output_auto_recovery_enabled" not in data
    assert "ac_charge_cable_safety_enabled" not in data
    assert "low_battery_alarm_enabled" not in data
    assert "low_battery_alarm_threshold_percent" not in data

def test_power_2000_off_peak_step_is_model_profile_not_runtime_candidate():
    power_2000 = capabilities.capabilities_for_model_code(0x94)
    power_1000_mini = capabilities.capabilities_for_model_code(0x98)

    assert power_2000.off_peak_charging_power_step_w == 10
    assert power_1000_mini.off_peak_charging_power_step_w is None


def test_0x1018_offset_34_is_retained_as_diagnostic_candidate_only():
    value = bytearray(0x56)
    value[1] = 0x02
    value[2] = 0x01
    value[3] = 0x01
    value[4:8] = (1500).to_bytes(4, "little")
    value[8:12] = (600).to_bytes(4, "little")
    value[12:16] = (1000).to_bytes(4, "little")
    value[34:38] = (10).to_bytes(4, "little")

    cfg = protocol.parse_power_config(tlv(0x1018, bytes(value)), source_cmd_id=0x60)
    assert cfg.unknown_0x1018_step_candidate_w == 10
    assert cfg.as_dict()["unknown_0x1018_step_candidate_w"] == 10


def test_off_peak_power_uses_explicit_step_from_minimum():
    value = bytearray(0x56)
    value[4:8] = (1500).to_bytes(4, "little")
    value[8:12] = (625).to_bytes(4, "little")
    value[12:16] = (625).to_bytes(4, "little")

    updated = protocol.update_0x1018_off_peak_power(
        bytes(value), 635, step_w=10
    )
    assert int.from_bytes(updated[12:16], "little") == 635

    with pytest.raises(ValueError, match="10W step from 625W"):
        protocol.update_0x1018_off_peak_power(bytes(value), 630, step_w=10)
