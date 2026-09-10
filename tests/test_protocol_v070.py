from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "dji_power_bt"

pkg = sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
pkg.__path__ = []
subpkg = sys.modules.setdefault(
    "custom_components.dji_power_bt",
    types.ModuleType("custom_components.dji_power_bt"),
)
subpkg.__path__ = [str(ROOT)]


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


load("const")
protocol = load("protocol")
tariff = load("tariff")


def tlv(tlv_id: int, value: bytes) -> bytes:
    return tlv_id.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def test_all_day_tariff_write_matches_verified_power_2000_shape() -> None:
    payload, slots = protocol.build_0x63_tariff_payload("off_peak")
    expected_body = bytes.fromhex(
        "0e 10 0c 00 0a 00 31 38 30 30 65 66 66 66 66 66 "
        "16 10 1c 00 "
        "16 00 0a 00 02 01 7f 00 00 00 00 00 17 3b "
        "16 00 0a 00 02 01 7f 00 00 00 17 3b 00 00"
    )
    assert payload[:4] == b"\x00\x00\x10\x00"
    assert payload[16:] == expected_body
    assert [(slot.start_time, slot.end_time) for slot in slots] == [
        ("00:00", "23:59"),
        ("23:59", "00:00"),
    ]
    assert protocol.classify_tariff_schedule(slots) == "all_day_off_peak"


def test_all_day_peak_profile_and_non_preset_classification() -> None:
    peak = protocol.make_all_day_tariff_slots("peak")
    assert protocol.classify_tariff_schedule(peak) == "all_day_peak"
    assert (
        protocol.classify_tariff_schedule([protocol.make_all_day_tariff_slot("peak")])
        == "other"
    )

    split = [
        protocol.TariffSlot(1, 1, 0x7F, "00 00 00", "00:00", "12:00"),
        protocol.TariffSlot(1, 1, 0x7F, "00 00 00", "12:00", "23:59"),
    ]
    assert protocol.classify_tariff_schedule(split) == "other"
    assert protocol.classify_tariff_schedule([]) == "other"


def test_custom_tariff_schedule_write_encodes_weekdays_and_times() -> None:
    slots = protocol.make_tariff_slots_from_periods(
        [
            {
                "tariff": "off_peak",
                "weekdays": ["mon", "tue", "wed", "thu", "fri"],
                "start_time": "23:00:00",
                "end_time": "07:00:00",
            },
            {
                "tariff": "peak",
                "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "start_time": "07:00",
                "end_time": "23:00",
            },
        ]
    )
    payload, written = protocol.build_0x63_tariff_schedule_payload(slots)

    assert payload[16:] == bytes.fromhex(
        "0e 10 0c 00 0a 00 31 38 30 30 65 66 66 66 66 66 "
        "16 10 1c 00 "
        "16 00 0a 00 02 02 1f 00 00 00 17 00 07 00 "
        "16 00 0a 00 01 01 7f 00 00 00 07 00 17 00"
    )
    assert written[0].day_mode == "day_mask"
    assert written[0].days == ["mon", "tue", "wed", "thu", "fri"]
    assert written[0].start_time == "23:00"
    assert written[0].end_time == "07:00"


def test_custom_tariff_schedule_rejects_overlap_and_subminute_precision() -> None:
    import pytest

    with pytest.raises(ValueError, match="must not overlap"):
        protocol.make_tariff_slots_from_periods(
            [
                {
                    "tariff": "peak",
                    "weekdays": ["mon"],
                    "start_time": "08:00",
                    "end_time": "12:00",
                },
                {
                    "tariff": "off_peak",
                    "weekdays": ["mon"],
                    "start_time": "11:00",
                    "end_time": "13:00",
                },
            ]
        )

    with pytest.raises(ValueError, match="whole-minute precision"):
        protocol.make_tariff_slots_from_periods(
            [
                {
                    "tariff": "peak",
                    "weekdays": ["mon"],
                    "start_time": "08:00:01",
                    "end_time": "12:00:00",
                }
            ]
        )


def test_tariff_schedule_signature_is_order_independent() -> None:
    slots = protocol.make_all_day_tariff_slots("peak")
    assert protocol.tariff_schedule_signature(slots) == (
        protocol.tariff_schedule_signature(list(reversed(slots)))
    )


def test_tariff_write_ack_accepts_0x1016() -> None:
    ack = protocol.build_keyed_header(timestamp_ms=1) + tlv(
        0x100E, (0).to_bytes(4, "little")
    ) + tlv(0x1016, (0).to_bytes(4, "little"))
    result = protocol.parse_0x63_write_result(ack)
    assert protocol.write_result_ok(result, 0x1016)


def test_two_slot_all_day_presets_cover_last_minute_without_conflict() -> None:
    for kind in ("peak", "off_peak"):
        slots = protocol.make_all_day_tariff_slots(kind)
        for hour, minute, expected_start in (
            (23, 58, "00:00"),
            (23, 59, "23:59"),
            (0, 0, "00:00"),
        ):
            result = tariff.evaluate_tariff_period(
                slots,
                datetime(2026, 8, 3, hour, minute, tzinfo=timezone.utc),
            )
            assert result.state == kind
            assert result.active_slot is not None
            assert result.active_slot["start_time"] == expected_start
            assert result.conflict is False
            assert result.next_change is None


def test_single_0000_2359_slot_does_not_cover_last_minute() -> None:
    slot = protocol.make_all_day_tariff_slot("peak")
    result = tariff.evaluate_tariff_period(
        [slot], datetime(2026, 8, 3, 23, 59, tzinfo=timezone.utc)
    )
    assert result.state == "none"
    assert result.next_change == datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc)
    assert result.next_period == "peak"


def test_0x66_hms_empty_and_one_record_shapes() -> None:
    empty = bytes.fromhex(
        "00 00 10 00 1b 9e ca 4c 9f 01 00 00 00 00 00 00 "
        "00 00 00 00"
    )
    report = protocol.parse_0x66_hms(empty)
    assert report.parse_status == "empty"
    assert report.declared_record_count == 0
    assert report.records == ()

    one = bytes.fromhex(
        "00 00 10 00 e1 93 60 4e 9f 01 00 00 00 00 00 00 "
        "00 00 01 00 37 00 00 28 03 00 00 00"
    )
    report = protocol.parse_0x66_hms(one)
    assert report.parse_status == "records_level_zero"
    assert report.declared_record_count == 1
    assert report.records[0].alarm_id == 0x28000037
    assert report.records[0].sensor_index == 3
    assert report.records[0].report_level == 0


def test_0x66_hms_nonzero_level_and_unknown_shape() -> None:
    nonzero = protocol.build_keyed_header(timestamp_ms=10) + bytes.fromhex(
        "00 00 01 00 78 56 34 12 02 03 00 00"
    )
    report = protocol.parse_0x66_hms(nonzero)
    assert report.parse_status == "records_nonzero_level"
    assert report.records[0].report_level == 3

    malformed = protocol.build_keyed_header(timestamp_ms=11) + bytes.fromhex(
        "00 00 02 00 78 56 34 12 02 03 00 00"
    )
    assert protocol.parse_0x66_hms(malformed).parse_status == "unrecognized"


def test_0x66_pattern_history_ignores_header_timestamp_and_tracks_transitions() -> None:
    history: deque[dict] = deque(maxlen=20)
    body = bytes.fromhex("00 00 01 00 37 00 00 28 03 00 00 00")
    first = protocol.parse_0x66_hms(protocol.build_keyed_header(timestamp_ms=1) + body)
    second = protocol.parse_0x66_hms(protocol.build_keyed_header(timestamp_ms=2) + body)
    protocol.update_hms_pattern_history(history, first, observed_at="2026-08-03T00:00:00Z")
    protocol.update_hms_pattern_history(history, second, observed_at="2026-08-03T00:00:01Z")

    assert len(history) == 1
    assert history[0]["occurrence_count"] == 2
    assert "timestamp_ms" not in history[0]["parse"]

    empty = protocol.parse_0x66_hms(
        protocol.build_keyed_header(timestamp_ms=3) + b"\x00\x00\x00\x00"
    )
    protocol.update_hms_pattern_history(history, empty, observed_at="2026-08-03T00:00:02Z")
    assert len(history) == 2
    assert history[-1]["parse"]["parse_status"] == "empty"


def test_power_2000_0x3030_ac_inlet_and_outlet_records_from_diagnostic() -> None:
    # Captured from the supplied Power 2000 diagnostic (0x61, 2026-08-04).
    payload = bytes.fromhex(
        "01 00 10 00 18 91 5e ca 9f 01 00 00 00 00 00 00 "
        "40 30 09 00 07 00 30 35 30 30 31 62 00 "
        "10 30 26 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "20 30 0c 00 6c 07 34 17 02 6c 07 00 00 02 0d 01 "
        "30 30 42 00 6e 01 7e 01 "
        "31 30 3a 00 "
        "32 30 19 00 01 33 30 14 00 34 30 10 00 "
        "01 01 00 00 00 78 01 00 38 30 00 00 35 30 00 00 "
        "32 30 19 00 02 33 30 14 00 34 30 10 00 "
        "01 02 00 68 01 00 00 00 38 30 00 00 35 30 00 00 "
        "50 30 07 00 02 01 02 02 00 00 00"
    )

    metrics = protocol.parse_realtime_metrics(payload)

    assert metrics.input_power_w == 382
    assert metrics.output_power_w == 366
    assert metrics.ac_inlet_input_power_w == 376
    assert metrics.ac_inlet_output_power_w == 0
    assert metrics.ac_outlet_input_power_w == 0
    assert metrics.ac_outlet_output_power_w == 360
    assert metrics.group_input_power_w == {"ac_inlet": 376, "ac_outlet": 0}
    assert metrics.group_output_power_w == {"ac_inlet": 0, "ac_outlet": 360}
    assert metrics.raw_records[0]["group_name"] == "ac_inlet"
    assert metrics.raw_records[0]["interface_name"] == "ac_inlet"
    assert metrics.raw_records[1]["group_name"] == "ac_outlet"
    assert metrics.raw_records[1]["interface_name"] == "ac_outlet"
