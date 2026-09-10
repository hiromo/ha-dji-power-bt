from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "dji_power_bt"
# Locally administered unicast address reserved for tests; not tied to hardware.
TEST_BLE_ADDRESS = "02:00:00:00:00:01"
TEST_BLE_ADDRESS_BYTES = bytes.fromhex("02 00 00 00 00 01")

# Load protocol helpers without importing Home Assistant-dependent package __init__.
pkg = types.ModuleType("custom_components")
pkg.__path__ = []
sys.modules.setdefault("custom_components", pkg)
subpkg = types.ModuleType("custom_components.dji_power_bt")
subpkg.__path__ = [str(ROOT)]
sys.modules.setdefault("custom_components.dji_power_bt", subpkg)


def load(name: str):
    fq = f"custom_components.dji_power_bt.{name}"
    spec = importlib.util.spec_from_file_location(fq, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fq] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


const = load("const")
protocol = load("protocol")
capabilities = load("capabilities")
tariff = load("tariff")
cloud = load("cloud")


def tlv(tlv_id: int, value: bytes) -> bytes:
    return tlv_id.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def leaf(port: int, interface: int, output_w: int, input_w: int, switch: int = 1) -> bytes:
    value = bytes([port, interface, switch]) + output_w.to_bytes(2, "little") + input_w.to_bytes(2, "little")
    return tlv(0x3034, value)


def group(group_type: int, *leaves: bytes) -> bytes:
    return tlv(0x3031, tlv(0x3032, bytes([group_type]) + tlv(0x3033, b"".join(leaves))))


def test_manufacturer_model_detection():
    adv = protocol.parse_manufacturer_data(
        bytes.fromhex("94 10 00") + TEST_BLE_ADDRESS_BYTES
    )
    assert adv.model_code == 0x94
    assert adv.model == "DJI Power 2000"
    assert adv.bound is True
    assert adv.mac_candidate == TEST_BLE_ADDRESS
    assert capabilities.capabilities_for_model_code(0x94).usb_a_ports == 4
    assert capabilities.capabilities_for_model_code(0x98).usb_c_input is True


def test_firmware_and_timezone_config_decode():
    base = bytearray(40)
    base[7:23] = b"01.00.1100\x00".ljust(16, b"\x00")
    base[24:40] = b"03.03.0000\x00".ljust(16, b"\x00")
    payload = tlv(0x1000, bytes(base)) + tlv(0x1015, int(540).to_bytes(2, "little", signed=True))
    cfg = protocol.parse_power_config(payload, source_cmd_id=0x60)
    assert cfg.firmware == "01.00.1100"
    assert cfg.secondary_firmware == "03.03.0000"
    assert cfg.timezone_offset_min == 540


def test_usb_group_aggregates_and_missing_port_semantics():
    value = (
        (15).to_bytes(2, "little")
        + (20).to_bytes(2, "little")
        + group(
            3,
            leaf(1, 3, 5, 0),
            leaf(1, 4, 10, 20),
        )
    )
    metrics = protocol.RealtimeMetrics()
    protocol.parse_0x3030_power_metrics(value, metrics)
    assert metrics.power_telemetry_present is True
    assert metrics.usb_output_power_w == 15
    assert metrics.usb_input_power_w == 20
    assert metrics.usb_a_1_output_power_w == 5
    assert metrics.usb_a_2_output_power_w is None
    assert metrics.usb_c_1_input_power_w == 20
    assert metrics.usb_c_1_output_power_w == 10
    assert metrics.usb_c_2_input_power_w is None
    assert metrics.reported_ports["usb_a"] == (1,)
    assert metrics.reported_ports["usb_c"] == (1,)


def test_sdc_individual_ports_and_totals():
    value = (
        (7).to_bytes(2, "little")
        + (111).to_bytes(2, "little")
        + group(4, leaf(1, 5, 0, 50), leaf(2, 5, 7, 61))
    )
    metrics = protocol.RealtimeMetrics()
    protocol.parse_0x3030_power_metrics(value, metrics)
    assert metrics.sdc_input_power_w == 111
    assert metrics.sdc_output_power_w == 7
    assert metrics.sdc_1_input_power_w == 50
    assert metrics.sdc_2_input_power_w == 61
    assert metrics.sdc_1_output_power_w == 0
    assert metrics.sdc_2_output_power_w == 7


def test_tariff_uses_supplied_aware_device_time():
    from datetime import datetime, timezone, timedelta

    slot = protocol.TariffSlot(
        kind_raw=2,
        day_mode_raw=2,
        day_mask=0x01,
        reserved_hex="00 00 00",
        start_time="18:15",
        end_time="06:30",
    )
    jst = timezone(timedelta(hours=9))
    monday_evening = datetime(2026, 7, 27, 20, 0, tzinfo=jst)
    result = tariff.evaluate_tariff_period([slot], monday_evening)
    assert result.state == "off_peak"
    assert result.next_change is not None
    assert result.next_change.tzinfo == jst


def test_parse_manufacturer_data_with_company_prefix() -> None:
    payload = bytes.fromhex("aa 08 94 10 00") + TEST_BLE_ADDRESS_BYTES
    parsed = protocol.parse_manufacturer_data(payload)
    assert parsed.model_code == 0x94
    assert parsed.bound is True
    assert parsed.mac_candidate == TEST_BLE_ADDRESS



def test_cloud_device_pair_key_is_strict_hex() -> None:
    payload = {
        "data": {
            "dy_devices": [
                {
                    "base_info": {"name": "Power 2000", "sn": "SERIAL"},
                    "pair_info": {
                        "pair_uuid": "uuid",
                        "pair_key": "0123456789abcdef0123456789ABCDEF",
                    },
                },
                {
                    "base_info": {"name": "invalid"},
                    "pair_info": {"pair_key": "z" * 32},
                },
            ]
        }
    }
    devices = cloud._extract_devices(payload)
    assert len(devices) == 1
    assert devices[0].pair_key == "0123456789abcdef0123456789abcdef"
