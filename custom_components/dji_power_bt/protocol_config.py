"""DJI Power configuration, tariff and write payload protocol."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import time as dt_time
import time
from typing import Any

from .protocol_common import INTERFACE_TYPE_NAMES, u16le, u32le
from .protocol_frame import find_first_tlv, find_tlvs, iter_tlvs

DEFAULT_STATUS_REQUEST_PAYLOAD = bytes.fromhex(
    "0000"
    "1002"
    "1003"
    "1005"
    "1006"
    "1007"
    "1008"
    "1009"
    "100a"
    "100b"
    "100c"
    "100d"
    "100e"
    "1015"
    "1016"
    "1018"
    "1019"
    "101b"
    "101e"
    "1020"
    "1022"
    "1023"
    "1024"
    "1025"
)


@dataclass(slots=True)
class TariffSlot:
    kind_raw: int
    day_mode_raw: int
    day_mask: int
    reserved_hex: str
    start_time: str
    end_time: str

    @property
    def kind(self) -> str:
        return {0x01: "peak", 0x02: "off_peak"}.get(
            self.kind_raw, f"unknown(0x{self.kind_raw:02x})"
        )

    @property
    def kind_ja(self) -> str:
        return {0x01: "ピーク", 0x02: "オフピーク"}.get(
            self.kind_raw, f"不明(0x{self.kind_raw:02x})"
        )

    @property
    def day_mode(self) -> str:
        return {0x01: "everyday", 0x02: "day_mask"}.get(
            self.day_mode_raw, f"unknown(0x{self.day_mode_raw:02x})"
        )

    @property
    def days(self) -> list[str]:
        return decode_day_mask(self.day_mask)

    @property
    def days_ja(self) -> str:
        return decode_day_mask_ja(self.day_mask)

    def summary_ja(self) -> str:
        return f"{self.kind_ja} {self.days_ja} {self.start_time}-{self.end_time}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind_raw": self.kind_raw,
            "kind": self.kind,
            "day_mode_raw": self.day_mode_raw,
            "day_mode": self.day_mode,
            "day_mask": self.day_mask,
            "days": self.days,
            "days_ja": self.days_ja,
            "reserved_hex": self.reserved_hex,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


TARIFF_SCHEDULE_PROFILE_ALL_DAY_PEAK = "all_day_peak"
TARIFF_SCHEDULE_PROFILE_ALL_DAY_OFF_PEAK = "all_day_off_peak"
TARIFF_SCHEDULE_PROFILE_OTHER = "other"
TARIFF_SCHEDULE_PROFILE_OPTIONS = (
    TARIFF_SCHEDULE_PROFILE_ALL_DAY_PEAK,
    TARIFF_SCHEDULE_PROFILE_ALL_DAY_OFF_PEAK,
    TARIFF_SCHEDULE_PROFILE_OTHER,
)

TARIFF_PRESET_ALL_DAY_PEAK = "all_day_peak"
TARIFF_PRESET_ALL_DAY_OFF_PEAK = "all_day_off_peak"
TARIFF_PRESET_OPTIONS = (
    TARIFF_PRESET_ALL_DAY_PEAK,
    TARIFF_PRESET_ALL_DAY_OFF_PEAK,
)
TARIFF_WEEKDAY_BITS = {
    "mon": 0x01,
    "tue": 0x02,
    "wed": 0x04,
    "thu": 0x08,
    "fri": 0x10,
    "sat": 0x20,
    "sun": 0x40,
}
# Each tariff slot occupies 14 payload bytes including its nested TLV header.
# Keeping the public action below 64 slots leaves room for the keyed header,
# companion record, outer table TLV and DUM framing within the 10-bit length.
MAX_TARIFF_SLOTS = 64


def make_all_day_tariff_slot(kind: str) -> TariffSlot:
    """Return the primary 00:00-23:59 record for compatibility."""
    return make_all_day_tariff_slots(kind)[0]


def make_all_day_tariff_slots(kind: str) -> list[TariffSlot]:
    """Return the two all-week records needed for complete 24-hour coverage."""
    kind_raw = {"peak": 0x01, "off_peak": 0x02}.get(kind)
    if kind_raw is None:
        raise ValueError(f"unsupported tariff kind: {kind}")
    return [
        TariffSlot(
            kind_raw=kind_raw,
            day_mode_raw=0x01,
            day_mask=0x7F,
            reserved_hex="00 00 00",
            start_time=start_time,
            end_time=end_time,
        )
        for start_time, end_time in (
            ("00:00", "23:59"),
            ("23:59", "00:00"),
        )
    ]


def make_tariff_slots_from_preset(preset: str) -> list[TariffSlot]:
    """Return the verified complete tariff table for one public preset."""
    kind = {
        TARIFF_PRESET_ALL_DAY_PEAK: "peak",
        TARIFF_PRESET_ALL_DAY_OFF_PEAK: "off_peak",
    }.get(preset)
    if kind is None:
        raise ValueError(f"unsupported tariff preset: {preset}")
    return make_all_day_tariff_slots(kind)


def _normalize_tariff_time(value: Any, *, field_name: str) -> str:
    """Return an HH:MM value and reject precision the device cannot store."""
    if isinstance(value, dt_time):
        hour = value.hour
        minute = value.minute
        second = value.second
        microsecond = value.microsecond
    elif isinstance(value, str):
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            raise ValueError(f"{field_name} must use HH:MM or HH:MM:SS")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2]) if len(parts) == 3 else 0
        except ValueError as err:
            raise ValueError(
                f"{field_name} must use numeric HH:MM or HH:MM:SS"
            ) from err
        microsecond = 0
    else:
        raise ValueError(f"{field_name} must be a time string")

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"{field_name} is outside the valid time-of-day range")
    if second != 0 or microsecond != 0:
        raise ValueError(f"{field_name} must use whole-minute precision")
    return f"{hour:02d}:{minute:02d}"


def _tariff_slot_weekdays(slot: TariffSlot) -> tuple[int, ...]:
    if slot.day_mode_raw == 0x01 and slot.day_mask == 0x7F:
        return tuple(range(7))
    if slot.day_mode_raw != 0x02 or not (1 <= slot.day_mask <= 0x7F):
        raise ValueError("tariff slot has an unsupported weekday mode or mask")
    return tuple(
        weekday for weekday in range(7) if slot.day_mask & (1 << weekday)
    )


def validate_tariff_slots(slots: Sequence[TariffSlot]) -> None:
    """Validate a complete writable tariff table before encoding it."""
    if not slots:
        raise ValueError("at least one tariff period is required")
    if len(slots) > MAX_TARIFF_SLOTS:
        raise ValueError(f"at most {MAX_TARIFF_SLOTS} tariff periods are supported")

    coverage = [False] * (7 * 24 * 60)
    for slot in slots:
        if slot.kind_raw not in {0x01, 0x02}:
            raise ValueError("tariff must be peak or off_peak")
        if slot.reserved_hex.lower() != "00 00 00":
            raise ValueError("tariff slot contains unsupported reserved bytes")

        start_time = _normalize_tariff_time(
            slot.start_time, field_name="start_time"
        )
        end_time = _normalize_tariff_time(slot.end_time, field_name="end_time")
        start_hour, start_minute = (int(part) for part in start_time.split(":"))
        end_hour, end_minute = (int(part) for part in end_time.split(":"))
        start_of_day = start_hour * 60 + start_minute
        end_of_day = end_hour * 60 + end_minute
        if start_of_day == end_of_day:
            raise ValueError(
                "start_time and end_time must differ; use an all-day preset "
                "for complete-day coverage"
            )

        for weekday in _tariff_slot_weekdays(slot):
            start = weekday * 24 * 60 + start_of_day
            end = weekday * 24 * 60 + end_of_day
            if end < start:
                end += 24 * 60
            for absolute_minute in range(start, end):
                index = absolute_minute % len(coverage)
                if coverage[index]:
                    raise ValueError("tariff periods must not overlap")
                coverage[index] = True


def make_tariff_slots_from_periods(
    periods: Sequence[Mapping[str, Any]],
) -> list[TariffSlot]:
    """Normalize public action period objects into writable tariff slots."""
    if not periods:
        raise ValueError("at least one tariff period is required")
    if len(periods) > MAX_TARIFF_SLOTS:
        raise ValueError(f"at most {MAX_TARIFF_SLOTS} tariff periods are supported")

    slots: list[TariffSlot] = []
    for index, period in enumerate(periods):
        if not isinstance(period, Mapping):
            raise ValueError(f"periods[{index}] must be an object")

        kind_raw = {"peak": 0x01, "off_peak": 0x02}.get(period.get("tariff"))
        if kind_raw is None:
            raise ValueError(f"periods[{index}].tariff must be peak or off_peak")

        weekdays_value = period.get("weekdays")
        if not isinstance(weekdays_value, Sequence) or isinstance(
            weekdays_value, (str, bytes)
        ):
            raise ValueError(f"periods[{index}].weekdays must be a list")
        weekdays = list(weekdays_value)
        if not weekdays:
            raise ValueError(f"periods[{index}].weekdays must not be empty")
        if any(not isinstance(day, str) for day in weekdays):
            raise ValueError(f"periods[{index}].weekdays must contain strings")
        if len(weekdays) != len(set(weekdays)):
            raise ValueError(f"periods[{index}].weekdays contains duplicates")
        unknown_weekdays = [day for day in weekdays if day not in TARIFF_WEEKDAY_BITS]
        if unknown_weekdays:
            raise ValueError(
                f"periods[{index}].weekdays contains unsupported values: "
                f"{unknown_weekdays}"
            )
        day_mask = 0
        for weekday in weekdays:
            day_mask |= TARIFF_WEEKDAY_BITS[weekday]

        slots.append(
            TariffSlot(
                kind_raw=kind_raw,
                day_mode_raw=0x01 if day_mask == 0x7F else 0x02,
                day_mask=day_mask,
                reserved_hex="00 00 00",
                start_time=_normalize_tariff_time(
                    period.get("start_time"),
                    field_name=f"periods[{index}].start_time",
                ),
                end_time=_normalize_tariff_time(
                    period.get("end_time"),
                    field_name=f"periods[{index}].end_time",
                ),
            )
        )

    validate_tariff_slots(slots)
    return slots


def tariff_schedule_signature(
    slots: Sequence[TariffSlot] | None,
) -> tuple[tuple[int, int, int, str, str, str], ...] | None:
    """Return an order-independent exact signature for full-table comparison."""
    if slots is None:
        return None
    return tuple(
        sorted(
            (
                slot.kind_raw,
                slot.day_mode_raw,
                slot.day_mask,
                slot.reserved_hex.lower(),
                slot.start_time,
                slot.end_time,
            )
            for slot in slots
        )
    )


def classify_tariff_schedule(slots: list[TariffSlot] | None) -> str:
    """Classify the whole tariff table against the two verified presets.

    This intentionally uses exact structural matching rather than semantic
    coverage. A user-created multi-slot table that happens to cover the whole
    week remains ``other`` and is never mistaken for a DJI Home preset.
    """
    if slots is None or len(slots) != 2:
        return TARIFF_SCHEDULE_PROFILE_OTHER
    expected_periods = (("00:00", "23:59"), ("23:59", "00:00"))
    if any(
        slot.day_mode_raw != 0x01
        or slot.day_mask != 0x7F
        or slot.reserved_hex.lower() != "00 00 00"
        or (slot.start_time, slot.end_time) != expected_period
        for slot, expected_period in zip(slots, expected_periods, strict=True)
    ):
        return TARIFF_SCHEDULE_PROFILE_OTHER
    kinds = {slot.kind_raw for slot in slots}
    if kinds == {0x01}:
        return TARIFF_SCHEDULE_PROFILE_ALL_DAY_PEAK
    if kinds == {0x02}:
        return TARIFF_SCHEDULE_PROFILE_ALL_DAY_OFF_PEAK
    return TARIFF_SCHEDULE_PROFILE_OTHER


@dataclass(slots=True)
class OutputInterfaceState:
    """One output-interface state record inside configuration key 0x100D."""

    read_tlv_id: int
    interface_type: int
    port_index: int
    raw_state: int
    raw_value: bytes

    @property
    def enabled(self) -> bool | None:
        if self.raw_state == 0x01:
            return True
        if self.raw_state == 0x02:
            return False
        return None

    @property
    def interface_name(self) -> str:
        return INTERFACE_TYPE_NAMES.get(
            self.interface_type, f"unknown_0x{self.interface_type:02x}"
        )

    def value_with_state(self, enabled: bool) -> bytes:
        if len(self.raw_value) < 3:
            raise ValueError("output-interface record is too short")
        value = bytearray(self.raw_value)
        value[2] = 0x01 if enabled else 0x02
        return bytes(value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "read_tlv_id": f"0x{self.read_tlv_id:04x}",
            "interface_type": self.interface_type,
            "interface_name": self.interface_name,
            "port_index": self.port_index,
            "raw_state": self.raw_state,
            "enabled": self.enabled,
            "raw_value_hex": self.raw_value.hex(" "),
        }


@dataclass(slots=True)
class ChargingModeOption:
    """One selectable charging-mode record inside configuration key 0x101E."""

    read_tlv_id: int
    raw_id: int
    nominal_power_w: int
    selection_raw: int
    raw_value: bytes

    @property
    def selected(self) -> bool | None:
        if self.selection_raw == 0x01:
            return True
        if self.selection_raw == 0x02:
            return False
        return None

    @property
    def key(self) -> str:
        return {0x01: "slow", 0x02: "fast"}.get(
            self.raw_id, f"mode_0x{self.raw_id:02x}"
        )

    def value_with_selection(self, selected: bool) -> bytes:
        if len(self.raw_value) < 6:
            raise ValueError("charging-mode record is too short")
        value = bytearray(self.raw_value)
        value[5] = 0x01 if selected else 0x02
        return bytes(value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "read_tlv_id": f"0x{self.read_tlv_id:04x}",
            "raw_id": self.raw_id,
            "key": self.key,
            "nominal_power_w": self.nominal_power_w,
            "selection_raw": self.selection_raw,
            "selected": self.selected,
            "raw_value_hex": self.raw_value.hex(" "),
        }


@dataclass(slots=True)
class PowerConfig:
    source_cmd_id: int
    source_payload: bytes

    firmware: str | None = None
    communication_module_firmware: str | None = None
    timezone_offset_min: int | None = None
    base_config_raw_hex: str | None = None

    tlv_1005_value: bytes | None = None
    tlv_1005_offset: int | None = None
    tlv_1006_value: bytes | None = None
    tlv_1006_offset: int | None = None

    tlv_100e_value: bytes | None = None
    tlv_100e_offset: int | None = None

    tlv_100d_value: bytes | None = None
    tlv_100d_offset: int | None = None
    output_interface_states: list[OutputInterfaceState] = field(default_factory=list)
    output_table_unparsed_hex: str | None = None

    tlv_1018_value: bytes | None = None
    tlv_1018_offset: int | None = None

    tlv_101e_value: bytes | None = None
    tlv_101e_offset: int | None = None
    charging_modes: list[ChargingModeOption] = field(default_factory=list)
    charging_modes_unparsed_hex: str | None = None

    charge_limit_max_percent: int | None = None
    charge_limit_min_percent: int | None = None
    charge_limit_percent: int | None = None
    discharge_limit_max_percent: int | None = None
    discharge_limit_min_percent: int | None = None
    discharge_limit_percent: int | None = None

    energy_saver_raw: int | None = None
    peak_discharge_raw: int | None = None
    off_peak_charge_raw: int | None = None

    off_peak_charge_power_max_w: int | None = None
    off_peak_charge_power_min_w: int | None = None
    off_peak_charging_power_w: int | None = None

    unknown_0x1018_power_w_at_30_candidate: int | None = None
    unknown_0x1018_step_candidate_w: int | None = None
    unknown_0x1018_power_block: list[dict[str, Any]] = field(default_factory=list)
    tariff_slots: list[TariffSlot] = field(default_factory=list)

    @property
    def secondary_firmware(self) -> str | None:
        """Backward-compatible internal alias used by older diagnostics/tests."""
        return self.communication_module_firmware

    @property
    def energy_optimization_mode(self) -> str:
        if self.energy_saver_raw == 0x01:
            return "disabled"
        if self.energy_saver_raw == 0x02:
            return "scheduled"
        if self.energy_saver_raw is None:
            return "unknown"
        return "unsupported"

    @property
    def energy_saver_text(self) -> str:
        return self.energy_optimization_mode

    @property
    def peak_discharge_enabled(self) -> bool | None:
        return _decode_on_off(self.peak_discharge_raw)

    @property
    def off_peak_charge_enabled(self) -> bool | None:
        return _decode_on_off(self.off_peak_charge_raw)

    def get_output_state(
        self, interface_type: int, port_index: int
    ) -> OutputInterfaceState | None:
        return next(
            (
                item
                for item in self.output_interface_states
                if item.interface_type == interface_type
                and item.port_index == port_index
            ),
            None,
        )

    @property
    def ac_output_raw(self) -> int | None:
        record = self.get_output_state(0x02, 1)
        return record.raw_state if record else None

    @property
    def ac_output_enabled(self) -> bool | None:
        record = self.get_output_state(0x02, 1)
        return record.enabled if record else None

    @property
    def sdc_raw(self) -> int | None:
        record = self.get_output_state(0x05, 1)
        return record.raw_state if record else None

    @property
    def sdc_enabled(self) -> bool | None:
        record = self.get_output_state(0x05, 1)
        return record.enabled if record else None

    @property
    def output_table_write_supported(self) -> bool:
        return bool(self.output_interface_states) and self.output_table_unparsed_hex is None

    @property
    def selected_charging_mode(self) -> ChargingModeOption | None:
        selected = [item for item in self.charging_modes if item.selected is True]
        return selected[0] if len(selected) == 1 else None

    @property
    def charging_mode(self) -> str | None:
        selected = self.selected_charging_mode
        return selected.key if selected else None

    @property
    def charging_mode_write_supported(self) -> bool:
        return bool(self.charging_modes) and self.charging_modes_unparsed_hex is None

    @property
    def tariff_summary(self) -> str | None:
        if not self.tariff_slots:
            return None
        return " / ".join(slot.summary_ja() for slot in self.tariff_slots)

    def as_dict(self) -> dict[str, Any]:
        return {
            "firmware": self.firmware,
            "communication_module_firmware": self.communication_module_firmware,
            "timezone_offset_min": self.timezone_offset_min,
            "base_config_raw_hex": self.base_config_raw_hex,
            "off_peak_charging_power_w": self.off_peak_charging_power_w,
            "off_peak_charge_power_min_w": self.off_peak_charge_power_min_w,
            "off_peak_charge_power_max_w": self.off_peak_charge_power_max_w,
            "charge_limit_percent": self.charge_limit_percent,
            "charge_limit_min_percent": self.charge_limit_min_percent,
            "charge_limit_max_percent": self.charge_limit_max_percent,
            "discharge_limit_percent": self.discharge_limit_percent,
            "discharge_limit_min_percent": self.discharge_limit_min_percent,
            "discharge_limit_max_percent": self.discharge_limit_max_percent,
            "off_peak_charge_raw": self.off_peak_charge_raw,
            "off_peak_charge_enabled": self.off_peak_charge_enabled,
            "peak_discharge_raw": self.peak_discharge_raw,
            "peak_discharge_enabled": self.peak_discharge_enabled,
            "energy_optimization_raw": self.energy_saver_raw,
            "energy_optimization_mode": self.energy_optimization_mode,
            "ac_output_raw": self.ac_output_raw,
            "ac_output_enabled": self.ac_output_enabled,
            "sdc_raw": self.sdc_raw,
            "sdc_enabled": self.sdc_enabled,
            "output_interface_states": [
                item.as_dict() for item in self.output_interface_states
            ],
            "output_table_unparsed_hex": self.output_table_unparsed_hex,
            "charging_mode": self.charging_mode,
            "charging_modes": [item.as_dict() for item in self.charging_modes],
            "charging_modes_unparsed_hex": self.charging_modes_unparsed_hex,
            "unknown_0x1018_power_w_at_30_candidate": self.unknown_0x1018_power_w_at_30_candidate,
            "unknown_0x1018_step_candidate_w": self.unknown_0x1018_step_candidate_w,
            "unknown_0x1018_power_block": self.unknown_0x1018_power_block,
            "tariff_slots": [slot.as_dict() for slot in self.tariff_slots],
            "tariff_summary": self.tariff_summary,
        }

    def summary(self) -> str:
        parts: list[str] = []
        if self.off_peak_charging_power_w is not None:
            parts.append(f"オフピーク充電電力={self.off_peak_charging_power_w} W")
        if self.charge_limit_percent is not None:
            parts.append(f"充電限度値={self.charge_limit_percent} %")
        if self.discharge_limit_percent is not None:
            parts.append(f"放電限度値={self.discharge_limit_percent} %")
        parts.append(f"AC出力={self.ac_output_enabled}")
        if self.sdc_enabled is not None:
            parts.append(f"SDC={self.sdc_enabled}")
        parts.append(f"エネルギー最適化={self.energy_optimization_mode}")
        if self.charging_mode is not None:
            parts.append(f"充電モード={self.charging_mode}")
        return ", ".join(parts)


INTERFACE_TYPE_NAMES: dict[int, str] = {0: "unknown", 1: "ac_inlet", 2: "ac_outlet", 3: "usb_a", 4: "usb_c", 5: "sdc", 6: "sdc_lite", 7: "12v", 8: "xt60"}
GROUP_TYPE_NAMES: dict[int, str] = {0: "unknown", 1: "ac_inlet", 2: "ac_outlet", 3: "usb", 4: "sdc", 5: "12v", 6: "xt60"}


def decode_day_mask(mask: int) -> list[str]:
    days = [
        (0x01, "mon"),
        (0x02, "tue"),
        (0x04, "wed"),
        (0x08, "thu"),
        (0x10, "fri"),
        (0x20, "sat"),
        (0x40, "sun"),
    ]
    return [name for bit, name in days if mask & bit]


def decode_day_mask_ja(mask: int) -> str:
    if mask == 0x7F:
        return "毎日"
    days = [
        (0x01, "月曜"),
        (0x02, "火曜"),
        (0x04, "水曜"),
        (0x08, "木曜"),
        (0x10, "金曜"),
        (0x20, "土曜"),
        (0x40, "日曜"),
    ]
    matched = [name for bit, name in days if mask & bit]
    return "+".join(matched) if matched else f"0x{mask:02x}"


def parse_0x1017_time_slot(value: bytes) -> TariffSlot | None:
    if len(value) < 10:
        return None
    return TariffSlot(
        kind_raw=value[0],
        day_mode_raw=value[1],
        day_mask=value[2],
        reserved_hex=value[3:6].hex(" "),
        start_time=f"{value[6]:02d}:{value[7]:02d}",
        end_time=f"{value[8]:02d}:{value[9]:02d}",
    )


def _decode_on_off(raw: int | None) -> bool | None:
    if raw == 0x01:
        return True
    if raw == 0x02:
        return False
    return None


def _parse_nested_records(
    value: bytes,
    *,
    expected_tlv_id: int,
    minimum_value_length: int,
) -> tuple[list[tuple[int, bytes]], str | None]:
    """Parse a complete sequence of nested TLVs without scanning payload bytes.

    Any malformed tail or unexpected nested TLV is retained as diagnostic hex and
    disables write-back of that table. This avoids silently deleting fields added
    by a future firmware.
    """
    records: list[tuple[int, bytes]] = []
    pos = 0
    while pos + 4 <= len(value):
        tlv_id = u16le(value, pos)
        length = u16le(value, pos + 2)
        end = pos + 4 + length
        if end > len(value):
            return records, value[pos:].hex(" ")
        record_value = value[pos + 4 : end]
        if tlv_id != expected_tlv_id or len(record_value) < minimum_value_length:
            return records, value[pos:].hex(" ")
        records.append((tlv_id, record_value))
        pos = end
    if pos != len(value):
        return records, value[pos:].hex(" ")
    return records, None


def parse_0x100d_output_states(
    value: bytes,
) -> tuple[list[OutputInterfaceState], str | None]:
    records, unparsed = _parse_nested_records(
        value, expected_tlv_id=0x1014, minimum_value_length=3
    )
    states = [
        OutputInterfaceState(
            read_tlv_id=tlv_id,
            interface_type=record_value[0],
            port_index=record_value[1],
            raw_state=record_value[2],
            raw_value=record_value,
        )
        for tlv_id, record_value in records
    ]
    return states, unparsed


def parse_0x101e_charging_modes(
    value: bytes,
) -> tuple[list[ChargingModeOption], str | None]:
    records, unparsed = _parse_nested_records(
        value, expected_tlv_id=0x101F, minimum_value_length=6
    )
    modes = [
        ChargingModeOption(
            read_tlv_id=tlv_id,
            raw_id=record_value[0],
            nominal_power_w=u32le(record_value, 1),
            selection_raw=record_value[5],
            raw_value=record_value,
        )
        for tlv_id, record_value in records
    ]
    return modes, unparsed


def _decode_ascii_version(value: bytes) -> str | None:
    text = value.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
    return text or None


def parse_power_config(payload: bytes, *, source_cmd_id: int) -> PowerConfig:
    cfg = PowerConfig(source_cmd_id=source_cmd_id, source_payload=payload)

    tlv_1000 = find_first_tlv(payload, 0x1000, min_length=40)
    if tlv_1000 is not None:
        _, value = tlv_1000
        cfg.base_config_raw_hex = value.hex(" ")
        cfg.firmware = _decode_ascii_version(value[7:23])
        cfg.communication_module_firmware = _decode_ascii_version(value[24:40])

    tlv_1015 = find_first_tlv(payload, 0x1015, expected_lengths={2}, min_length=2)
    if tlv_1015 is not None:
        _, value = tlv_1015
        cfg.timezone_offset_min = int.from_bytes(value[:2], "little", signed=True)

    tlv_1005 = find_first_tlv(payload, 0x1005, expected_lengths={0x18}, min_length=0x18)
    if tlv_1005 is not None:
        offset, value = tlv_1005
        cfg.tlv_1005_offset = offset
        cfg.tlv_1005_value = value
        values = [u32le(value, i) for i in range(0, len(value), 4)]
        if len(values) >= 6:
            cfg.charge_limit_max_percent = values[0]
            cfg.charge_limit_min_percent = values[1]
            cfg.charge_limit_percent = values[2]
            cfg.discharge_limit_max_percent = values[3]
            cfg.discharge_limit_min_percent = values[4]
            cfg.discharge_limit_percent = values[5]

    tlv_1006 = find_first_tlv(payload, 0x1006, expected_lengths={4}, min_length=4)
    if tlv_1006 is not None:
        cfg.tlv_1006_offset, cfg.tlv_1006_value = tlv_1006

    tlv_100e = find_first_tlv(payload, 0x100E, min_length=1)
    if tlv_100e is not None:
        cfg.tlv_100e_offset, cfg.tlv_100e_value = tlv_100e

    tlv_100d = find_first_tlv(payload, 0x100D, min_length=7)
    if tlv_100d is not None:
        cfg.tlv_100d_offset, cfg.tlv_100d_value = tlv_100d
        (
            cfg.output_interface_states,
            cfg.output_table_unparsed_hex,
        ) = parse_0x100d_output_states(tlv_100d[1])

    for _, slot_value in find_tlvs(payload, 0x1017, expected_lengths={0x0A}):
        slot = parse_0x1017_time_slot(slot_value)
        if slot is not None:
            cfg.tariff_slots.append(slot)

    tlv_1018 = find_first_tlv(payload, 0x1018, expected_lengths={0x56}, min_length=0x56)
    if tlv_1018 is not None:
        offset, value = tlv_1018
        cfg.tlv_1018_offset = offset
        cfg.tlv_1018_value = value
        if len(value) >= 4:
            cfg.energy_saver_raw = value[1]
            cfg.peak_discharge_raw = value[2]
            cfg.off_peak_charge_raw = value[3]
        if len(value) >= 16:
            cfg.off_peak_charge_power_max_w = u32le(value, 4)
            cfg.off_peak_charge_power_min_w = u32le(value, 8)
            cfg.off_peak_charging_power_w = u32le(value, 12)
        if len(value) >= 34:
            cfg.unknown_0x1018_power_w_at_30_candidate = u32le(value, 30)
        if len(value) >= 38:
            cfg.unknown_0x1018_step_candidate_w = u32le(value, 34)
        cfg.unknown_0x1018_power_block = parse_0x1018_unknown_power_block(value)

    tlv_101e = find_first_tlv(payload, 0x101E, min_length=10)
    if tlv_101e is not None:
        cfg.tlv_101e_offset, cfg.tlv_101e_value = tlv_101e
        (
            cfg.charging_modes,
            cfg.charging_modes_unparsed_hex,
        ) = parse_0x101e_charging_modes(tlv_101e[1])

    return cfg


def parse_0x1018_unknown_power_block(value: bytes) -> list[dict[str, Any]]:
    """Return human-readable candidates around the unexplained 0x1018 power block."""
    candidates: list[tuple[int, int, str]] = [
        (0x12, 4, "unknown_block_candidate_a_max_or_limit_w"),
        (0x16, 4, "unknown_block_candidate_a_min_w"),
        (0x1A, 4, "unknown_block_candidate_b_max_or_default_w"),
        (0x1E, 4, "unknown_0x1018_30_34_w_candidate"),
        (0x22, 4, "unknown_step_or_granularity_candidate"),
        (0x26, 4, "unknown_block_candidate_c_min_w"),
        (0x51, 4, "unknown_tail_power_w_candidate"),
    ]
    result: list[dict[str, Any]] = []
    for offset, length, name in candidates:
        if len(value) >= offset + length:
            raw = value[offset : offset + length]
            result.append(
                {
                    "offset": offset,
                    "name": name,
                    "raw_hex": raw.hex(" "),
                    "u32le": u32le(raw, 0),
                }
            )
    if len(value) >= 0x56:
        result.append({"offset": 0x55, "name": "unknown_tail_flag", "raw_hex": f"{value[0x55]:02x}", "u8": value[0x55]})
    return result


def update_0x1005_charge_limit(value: bytes, new_percent: int) -> bytes:
    if len(value) < 24:
        raise ValueError("0x1005 value too short")
    b = bytearray(value)
    max_percent = u32le(b, 0)
    min_percent = u32le(b, 4)
    if not (min_percent <= new_percent <= max_percent):
        raise ValueError(
            f"charge limit out of range: {new_percent}%, allowed {min_percent}-{max_percent}%"
        )
    b[8:12] = int(new_percent).to_bytes(4, "little")
    return bytes(b)


def update_0x1005_discharge_limit(value: bytes, new_percent: int) -> bytes:
    if len(value) < 24:
        raise ValueError("0x1005 value too short")
    b = bytearray(value)
    max_percent = u32le(b, 12)
    min_percent = u32le(b, 16)
    if not (min_percent <= new_percent <= max_percent):
        raise ValueError(
            f"discharge limit out of range: {new_percent}%, allowed {min_percent}-{max_percent}%"
        )
    b[20:24] = int(new_percent).to_bytes(4, "little")
    return bytes(b)


def update_0x1018_off_peak_power(value: bytes, new_w: int, *, step_w: int) -> bytes:
    if len(value) < 16:
        raise ValueError("0x1018 value too short")
    b = bytearray(value)
    max_w = u32le(b, 4)
    min_w = u32le(b, 8)
    if not (min_w <= new_w <= max_w):
        raise ValueError(f"out of range: {new_w}W, allowed {min_w}-{max_w}W")
    if step_w <= 0:
        raise ValueError("off-peak charging power step must be positive")
    if (new_w - min_w) % step_w != 0:
        raise ValueError(
            f"off-peak charging power must follow a {step_w}W step from {min_w}W"
        )
    # Confirmed current field. Do not touch 0x1018[30:34]; it is a different unknown value.
    b[12:16] = new_w.to_bytes(4, "little")
    return bytes(b)


def update_0x1018_off_peak_charge_enabled(value: bytes, enabled: bool) -> bytes:
    if len(value) < 4:
        raise ValueError("0x1018 value too short")
    b = bytearray(value)
    b[3] = 0x01 if enabled else 0x02
    return bytes(b)


def update_0x1018_peak_discharge_enabled(value: bytes, enabled: bool) -> bytes:
    if len(value) < 3:
        raise ValueError("0x1018 value too short")
    b = bytearray(value)
    b[2] = 0x01 if enabled else 0x02
    return bytes(b)


def update_0x1018_energy_optimization_mode(value: bytes, mode: str) -> bytes:
    if len(value) < 2:
        raise ValueError("0x1018 value too short")
    raw = {"disabled": 0x01, "scheduled": 0x02}.get(mode)
    if raw is None:
        raise ValueError(f"unsupported energy optimization mode: {mode}")
    b = bytearray(value)
    b[1] = raw
    return bytes(b)


def _make_tlv(tlv_id: int, value: bytes) -> bytes:
    return tlv_id.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def build_keyed_header(*, timestamp_ms: int | None = None) -> bytes:
    """Build the 16-byte keyed-command header used by 0x63 writes."""
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    return b"\x00\x00\x10\x00" + int(timestamp_ms).to_bytes(8, "little") + b"\x00" * 4


def make_0x100e_command_write_tlv() -> bytes:
    """Build the command companion record observed in DJI Home 0x63 writes."""
    return _make_tlv(0x100E, b"\x0a\x00" + b"1800efffff")


def make_0x1018_write_tlv(value_1018: bytes) -> bytes:
    return _make_tlv(0x1018, value_1018)


def _make_0x1016_tariff_table(slots: Sequence[TariffSlot]) -> bytes:
    """Build one complete tariff table from validated writable slots.

    Read reports expose each record as 0x1017, while writes wrap 0x0016 records
    inside an outer 0x1016 table.
    """
    validate_tariff_slots(slots)
    nested = bytearray()
    for slot in slots:
        start_hour, start_minute = (int(part) for part in slot.start_time.split(":"))
        end_hour, end_minute = (int(part) for part in slot.end_time.split(":"))
        nested += _make_tlv(
            0x0016,
            bytes(
                (
                    slot.kind_raw,
                    slot.day_mode_raw,
                    slot.day_mask,
                    0x00,
                    0x00,
                    0x00,
                    start_hour,
                    start_minute,
                    end_hour,
                    end_minute,
                )
            ),
        )
    return _make_tlv(0x1016, bytes(nested))


def _make_0x1016_all_day_tariff_table(
    kind: str,
) -> tuple[bytes, list[TariffSlot]]:
    """Build the verified two-record table required for a complete day."""
    slots = make_all_day_tariff_slots(kind)
    return _make_0x1016_tariff_table(slots), slots


def make_0x1016_tariff_table_write_tlv(kind: str) -> tuple[bytes, TariffSlot]:
    """Build the all-day table and return its primary slot for compatibility."""
    tariff_tlv, slots = _make_0x1016_all_day_tariff_table(kind)
    return tariff_tlv, slots[0]


def make_0x1005_write_tlv(value_1005: bytes) -> bytes:
    return _make_tlv(0x1005, value_1005)


def make_simple_write_tlv(tlv_id: int, value: bytes) -> bytes:
    return _make_tlv(tlv_id, value)


def make_0x100d_output_table_write_tlv(
    cfg: PowerConfig,
    *,
    interface_type: int,
    port_index: int,
    enabled: bool,
) -> tuple[bytes, list[OutputInterfaceState]]:
    """Build a full-table 0x100D read-modify-write payload.

    Every 0x1014 read record is emitted as a 0x000D write record, preserving
    order and all bytes except the target record's state byte.
    """
    if not cfg.output_table_write_supported:
        raise ValueError("complete 0x100D output table is not available")
    target_found = False
    nested = bytearray()
    updated_states: list[OutputInterfaceState] = []
    for item in cfg.output_interface_states:
        is_target = (
            item.interface_type == interface_type and item.port_index == port_index
        )
        record_value = item.value_with_state(enabled) if is_target else item.raw_value
        if is_target:
            target_found = True
        nested += _make_tlv(0x000D, record_value)
        updated_states.append(
            OutputInterfaceState(
                read_tlv_id=item.read_tlv_id,
                interface_type=item.interface_type,
                port_index=item.port_index,
                raw_state=record_value[2],
                raw_value=record_value,
            )
        )
    if not target_found:
        raise ValueError(
            f"output interface 0x{interface_type:02x}/{port_index} not reported"
        )
    return _make_tlv(0x100D, bytes(nested)), updated_states


def make_0x101e_charging_mode_write_tlv(
    cfg: PowerConfig, selected_key: str
) -> tuple[bytes, list[ChargingModeOption]]:
    if not cfg.charging_mode_write_supported:
        raise ValueError("complete 0x101E charging-mode table is not available")
    matching = [item for item in cfg.charging_modes if item.key == selected_key]
    if len(matching) != 1:
        raise ValueError(f"charging mode is not available: {selected_key}")
    nested = bytearray()
    updated_modes: list[ChargingModeOption] = []
    for item in cfg.charging_modes:
        record_value = item.value_with_selection(item.key == selected_key)
        nested += _make_tlv(0x001E, record_value)
        updated_modes.append(
            ChargingModeOption(
                read_tlv_id=item.read_tlv_id,
                raw_id=item.raw_id,
                nominal_power_w=item.nominal_power_w,
                selection_raw=record_value[5],
                raw_value=record_value,
            )
        )
    return _make_tlv(0x101E, bytes(nested)), updated_modes


def build_0x63_output_payload_from_config(
    cfg: PowerConfig,
    *,
    interface_type: int,
    port_index: int,
    enabled: bool,
) -> tuple[bytes, list[OutputInterfaceState]]:
    output_tlv, updated_states = make_0x100d_output_table_write_tlv(
        cfg,
        interface_type=interface_type,
        port_index=port_index,
        enabled=enabled,
    )
    payload = (
        build_keyed_header()
        + output_tlv
        + make_0x100e_command_write_tlv()
    )
    return payload, updated_states


def build_0x63_charging_mode_payload_from_config(
    cfg: PowerConfig, selected_key: str
) -> tuple[bytes, list[ChargingModeOption]]:
    mode_tlv, updated_modes = make_0x101e_charging_mode_write_tlv(
        cfg, selected_key
    )
    payload = (
        build_keyed_header()
        + make_0x100e_command_write_tlv()
        + mode_tlv
    )
    return payload, updated_modes


def build_0x63_tariff_payload(kind: str) -> tuple[bytes, list[TariffSlot]]:
    """Build the verified two-slot all-day peak/off-peak 0x63 payload."""
    tariff_tlv, slots = _make_0x1016_all_day_tariff_table(kind)
    return (
        build_keyed_header()
        + make_0x100e_command_write_tlv()
        + tariff_tlv,
        slots,
    )


def build_0x63_tariff_schedule_payload(
    slots: Sequence[TariffSlot],
) -> tuple[bytes, list[TariffSlot]]:
    """Build a complete arbitrary tariff-table 0x63 payload."""
    normalized_slots = list(slots)
    tariff_tlv = _make_0x1016_tariff_table(normalized_slots)
    return (
        build_keyed_header()
        + make_0x100e_command_write_tlv()
        + tariff_tlv,
        normalized_slots,
    )


def build_0x63_1005_payload_from_config(cfg: PowerConfig, new_1005_value: bytes) -> bytes:
    if cfg.tlv_1005_value is None:
        raise ValueError("0x1005 TLV not found in current config")
    payload = build_keyed_header() + make_0x1005_write_tlv(new_1005_value)
    if cfg.tlv_1006_value is not None:
        payload += make_simple_write_tlv(0x1006, cfg.tlv_1006_value)
    return payload + make_0x100e_command_write_tlv()


def build_0x63_payload_from_config(cfg: PowerConfig, new_1018_value: bytes) -> bytes:
    if cfg.tlv_1018_value is None:
        raise ValueError("0x1018 TLV not found in current config")
    return (
        build_keyed_header()
        + make_0x100e_command_write_tlv()
        + make_0x1018_write_tlv(new_1018_value)
    )


def parse_0x63_write_result(payload: bytes) -> dict[str, Any]:
    """Decode sequential per-property u32 result codes from a 0x63 response."""
    body = (
        payload[16:]
        if len(payload) >= 16 and payload[2:4] == b"\x10\x00"
        else payload
    )
    result: dict[str, Any] = {}
    supported = {
        0x1005,
        0x1006,
        0x100D,
        0x100E,
        0x1016,
        0x1018,
        0x101E,
        0x1023,
    }
    for tlv_id, _value_offset, value in iter_tlvs(body):
        if tlv_id in supported and len(value) == 4:
            result[f"write_status_0x{tlv_id:04x}"] = u32le(value, 0)
    return result


def write_result_ok(result: dict[str, Any], tlv_id: int = 0x1018) -> bool:
    return result.get(f"write_status_0x{tlv_id:04x}") == 0


# -----------------------------------------------------------------------------
# 0x61 realtime parsing
# -----------------------------------------------------------------------------
