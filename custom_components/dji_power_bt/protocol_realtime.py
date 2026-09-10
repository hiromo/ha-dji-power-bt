"""DJI Power realtime 0x61 telemetry parsing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .protocol_common import GROUP_TYPE_NAMES, INTERFACE_TYPE_NAMES, u16le, u32le
from .protocol_frame import find_first_tlv, find_tlvs, iter_tlvs

@dataclass(slots=True)
class RealtimeMetrics:
    soc_percent: float | None = None
    soc_duplicate_percent_candidate: float | None = None
    remaining_time_min: int | None = None
    battery_status_code: int | None = None
    battery_temperature_c: float | None = None
    battery_unit_count: int | None = None
    raw_0x3010_hex: str | None = None
    raw_0x3020_hex: str | None = None
    raw_0x3050_hex: str | None = None
    input_power_w: int | None = None
    output_power_w: int | None = None
    power_telemetry_present: bool = False
    ac_inlet_input_power_w: int | None = None
    ac_inlet_output_power_w: int | None = None
    ac_outlet_input_power_w: int | None = None
    ac_outlet_output_power_w: int | None = None
    usb_input_power_w: int | None = None
    usb_output_power_w: int | None = None
    # Interface aggregates remain available in diagnostics, but are not all
    # exposed as entities. USB group input/output is the normal HA aggregate.
    usb_a_input_power_w: int | None = None
    usb_a_output_power_w: int | None = None
    usb_a_1_input_power_w: int | None = None
    usb_a_1_output_power_w: int | None = None
    usb_a_2_input_power_w: int | None = None
    usb_a_2_output_power_w: int | None = None
    usb_a_3_input_power_w: int | None = None
    usb_a_3_output_power_w: int | None = None
    usb_a_4_input_power_w: int | None = None
    usb_a_4_output_power_w: int | None = None
    usb_c_input_power_w: int | None = None
    usb_c_output_power_w: int | None = None
    usb_c_1_input_power_w: int | None = None
    usb_c_1_output_power_w: int | None = None
    usb_c_2_input_power_w: int | None = None
    usb_c_2_output_power_w: int | None = None
    usb_c_3_input_power_w: int | None = None
    usb_c_3_output_power_w: int | None = None
    usb_c_4_input_power_w: int | None = None
    usb_c_4_output_power_w: int | None = None
    sdc_input_power_w: int | None = None
    sdc_output_power_w: int | None = None
    sdc_1_input_power_w: int | None = None
    sdc_1_output_power_w: int | None = None
    sdc_2_input_power_w: int | None = None
    sdc_2_output_power_w: int | None = None
    sdc_lite_input_power_w: int | None = None
    sdc_lite_output_power_w: int | None = None
    output_12v_power_w: int | None = None
    xt60_input_power_w: int | None = None
    xt60_output_power_w: int | None = None
    reported_interface_types: tuple[int, ...] = ()
    reported_ports: dict[str, tuple[int, ...]] = field(default_factory=dict)
    group_input_power_w: dict[str, int] = field(default_factory=dict)
    group_output_power_w: dict[str, int] = field(default_factory=dict)
    raw_records: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "soc_percent": self.soc_percent,
            "soc_duplicate_percent_candidate": self.soc_duplicate_percent_candidate,
            "remaining_time_min": self.remaining_time_min,
            "battery_status_code": self.battery_status_code,
            "battery_temperature_c": self.battery_temperature_c,
            "battery_unit_count": self.battery_unit_count,
            "raw_0x3010_hex": self.raw_0x3010_hex,
            "raw_0x3020_hex": self.raw_0x3020_hex,
            "raw_0x3050_hex": self.raw_0x3050_hex,
            "input_power_w": self.input_power_w,
            "input_minus_output_w": (
                self.input_power_w - self.output_power_w
                if self.input_power_w is not None and self.output_power_w is not None
                else None
            ),
            "output_power_w": self.output_power_w,
            "power_telemetry_present": self.power_telemetry_present,
            "ac_inlet_input_power_w": self.ac_inlet_input_power_w,
            "ac_inlet_output_power_w": self.ac_inlet_output_power_w,
            "ac_outlet_input_power_w": self.ac_outlet_input_power_w,
            "ac_outlet_output_power_w": self.ac_outlet_output_power_w,
            "usb_input_power_w": self.usb_input_power_w,
            "usb_output_power_w": self.usb_output_power_w,
            "usb_a_input_power_w": self.usb_a_input_power_w,
            "usb_a_output_power_w": self.usb_a_output_power_w,
            "usb_a_ports": {
                str(index): {
                    "input_power_w": getattr(self, f"usb_a_{index}_input_power_w"),
                    "output_power_w": getattr(self, f"usb_a_{index}_output_power_w"),
                }
                for index in range(1, 5)
            },
            "usb_c_input_power_w": self.usb_c_input_power_w,
            "usb_c_output_power_w": self.usb_c_output_power_w,
            "usb_c_ports": {
                str(index): {
                    "input_power_w": getattr(self, f"usb_c_{index}_input_power_w"),
                    "output_power_w": getattr(self, f"usb_c_{index}_output_power_w"),
                }
                for index in range(1, 5)
            },
            "sdc_input_power_w": self.sdc_input_power_w,
            "sdc_output_power_w": self.sdc_output_power_w,
            "sdc_ports": {
                str(index): {
                    "input_power_w": getattr(self, f"sdc_{index}_input_power_w"),
                    "output_power_w": getattr(self, f"sdc_{index}_output_power_w"),
                }
                for index in range(1, 3)
            },
            "sdc_lite_input_power_w": self.sdc_lite_input_power_w,
            "sdc_lite_output_power_w": self.sdc_lite_output_power_w,
            "output_12v_power_w": self.output_12v_power_w,
            "xt60_input_power_w": self.xt60_input_power_w,
            "xt60_output_power_w": self.xt60_output_power_w,
            "reported_interface_types": [
                {"raw": value, "name": INTERFACE_TYPE_NAMES.get(value, "unknown")}
                for value in self.reported_interface_types
            ],
            "reported_ports": {key: list(value) for key, value in self.reported_ports.items()},
            "group_input_power_w": self.group_input_power_w,
            "group_output_power_w": self.group_output_power_w,
            "raw_records": self.raw_records,
        }


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

def find_0x3030_tlv(payload: bytes) -> tuple[int, bytes] | None:
    candidates = find_tlvs(payload, 0x3030)
    for offset, value in candidates:
        if len(value) < 4:
            continue
        output_w = u16le(value, 0)
        input_w = u16le(value, 2)
        if output_w <= 5000 and input_w <= 5000:
            return offset, value
    return candidates[0] if candidates else None


def parse_0x3020_battery_metrics(value: bytes, metrics: RealtimeMetrics) -> None:
    if len(value) >= 2:
        metrics.soc_percent = u16le(value, 0) / 100.0
    if len(value) >= 4:
        metrics.remaining_time_min = u16le(value, 2)
    if len(value) >= 5:
        metrics.battery_status_code = value[4]
    if len(value) >= 9:
        metrics.soc_duplicate_percent_candidate = u32le(value, 5) / 100.0
    if len(value) >= 11:
        metrics.battery_temperature_c = u16le(value, 9) / 100.0
    if len(value) >= 12:
        metrics.battery_unit_count = value[11]


def _parse_0x3034_input_voltage(value: bytes) -> float | None:
    if len(value) < 8:
        return None
    for container_id, _, container_value in iter_tlvs(value[8:]):
        if container_id != 0x3035:
            continue
        for record_id, _, record_value in iter_tlvs(container_value):
            if record_id == 0x3036 and len(record_value) >= 3 and record_value[0] == 1:
                return u16le(record_value, 1) / 1000.0
    return None


def parse_0x3030_power_metrics(value: bytes, metrics: RealtimeMetrics) -> None:
    """Parse total, group, interface and per-port 0x3030 power telemetry.

    A missing individual 0x3034 record remains ``None`` so Home Assistant can
    distinguish an unreported/unplugged port from a reported 0 W port. Group and
    interface aggregate values are 0 W when a valid 0x3030 packet contains no
    matching record.
    """
    if len(value) < 4:
        return
    metrics.power_telemetry_present = True
    metrics.output_power_w = u16le(value, 0)
    metrics.input_power_w = u16le(value, 2)

    group_output: dict[int, int] = {}
    group_input: dict[int, int] = {}
    interface_output: dict[str, int] = {}
    interface_input: dict[str, int] = {}
    port_input: dict[str, dict[int, int]] = {"usb_a": {}, "usb_c": {}, "sdc": {}}
    port_output: dict[str, dict[int, int]] = {"usb_a": {}, "usb_c": {}, "sdc": {}}
    reported_types: set[int] = set()
    raw_records: list[dict[str, Any]] = []

    for tlv_id, _, tlv_value in iter_tlvs(value[4:]):
        if tlv_id != 0x3031:
            continue
        for rec_id, _, rec_value in iter_tlvs(tlv_value):
            if rec_id != 0x3032 or len(rec_value) < 1:
                continue
            group_type = rec_value[0]
            group_name = GROUP_TYPE_NAMES.get(group_type, "unknown")
            for inner_id, _, inner_value in iter_tlvs(rec_value[1:]):
                if inner_id != 0x3033:
                    continue
                for leaf_id, _, leaf_value in iter_tlvs(inner_value):
                    if leaf_id != 0x3034 or len(leaf_value) < 7:
                        continue
                    port_index = leaf_value[0]
                    interface_type = leaf_value[1]
                    switch_state = leaf_value[2]
                    interface_name = INTERFACE_TYPE_NAMES.get(interface_type, "unknown")
                    output_w = u16le(leaf_value, 3)
                    input_w = u16le(leaf_value, 5)
                    reported_types.add(interface_type)
                    record: dict[str, Any] = {
                        "group_type": group_type,
                        "group_name": group_name,
                        "port_index": port_index,
                        "interface_type": interface_type,
                        "interface_name": interface_name,
                        "switch_state": switch_state,
                        "enabled": switch_state == 1 if switch_state in (1, 2) else None,
                        "output_power_w": output_w,
                        "input_power_w": input_w,
                        "leaf_hex": leaf_value.hex(" "),
                    }
                    if (voltage := _parse_0x3034_input_voltage(leaf_value)) is not None:
                        record["input_voltage_v"] = voltage
                    raw_records.append(record)
                    group_output[group_type] = group_output.get(group_type, 0) + output_w
                    group_input[group_type] = group_input.get(group_type, 0) + input_w
                    interface_output[interface_name] = interface_output.get(interface_name, 0) + output_w
                    interface_input[interface_name] = interface_input.get(interface_name, 0) + input_w
                    if interface_name in port_input and port_index > 0:
                        port_input[interface_name][port_index] = input_w
                        port_output[interface_name][port_index] = output_w

    # Power 2000 validation against DJI Home shows that type 1 is the
    # physical AC inlet and type 2 is the AC outlet bank. Keep both directions
    # in diagnostics even though only inlet-input and outlet-output are exposed
    # as normal Home Assistant entities.
    metrics.ac_inlet_input_power_w = group_input.get(
        1, interface_input.get("ac_inlet", 0)
    )
    metrics.ac_inlet_output_power_w = group_output.get(
        1, interface_output.get("ac_inlet", 0)
    )
    metrics.ac_outlet_input_power_w = group_input.get(
        2, interface_input.get("ac_outlet", 0)
    )
    metrics.ac_outlet_output_power_w = group_output.get(
        2, interface_output.get("ac_outlet", 0)
    )

    # USB-A and USB-C share protocol group 0x03. These are the preferred
    # user-facing aggregates; interface-specific totals remain diagnostics-only.
    metrics.usb_input_power_w = group_input.get(3, interface_input.get("usb_a", 0) + interface_input.get("usb_c", 0))
    metrics.usb_output_power_w = group_output.get(3, interface_output.get("usb_a", 0) + interface_output.get("usb_c", 0))
    metrics.usb_a_input_power_w = interface_input.get("usb_a", 0)
    metrics.usb_a_output_power_w = interface_output.get("usb_a", 0)
    metrics.usb_c_input_power_w = interface_input.get("usb_c", 0)
    metrics.usb_c_output_power_w = interface_output.get("usb_c", 0)

    for interface_name in ("usb_a", "usb_c"):
        for index in range(1, 5):
            setattr(metrics, f"{interface_name}_{index}_input_power_w", port_input[interface_name].get(index))
            setattr(metrics, f"{interface_name}_{index}_output_power_w", port_output[interface_name].get(index))

    metrics.sdc_input_power_w = interface_input.get("sdc", 0)
    metrics.sdc_output_power_w = interface_output.get("sdc", 0)
    for index in range(1, 3):
        setattr(metrics, f"sdc_{index}_input_power_w", port_input["sdc"].get(index))
        setattr(metrics, f"sdc_{index}_output_power_w", port_output["sdc"].get(index))

    metrics.sdc_lite_input_power_w = interface_input.get("sdc_lite", 0)
    metrics.sdc_lite_output_power_w = interface_output.get("sdc_lite", 0)
    metrics.output_12v_power_w = interface_output.get("12v", 0)
    metrics.xt60_input_power_w = interface_input.get("xt60", 0)
    metrics.xt60_output_power_w = interface_output.get("xt60", 0)
    metrics.reported_interface_types = tuple(sorted(reported_types))
    metrics.reported_ports = {
        name: tuple(sorted(indexes))
        for name, indexes in ((name, port_output[name]) for name in port_output)
    }
    metrics.group_input_power_w = {
        GROUP_TYPE_NAMES.get(key, f"0x{key:02x}"): val for key, val in group_input.items()
    }
    metrics.group_output_power_w = {
        GROUP_TYPE_NAMES.get(key, f"0x{key:02x}"): val for key, val in group_output.items()
    }
    metrics.raw_records = raw_records


def parse_realtime_metrics(payload: bytes) -> RealtimeMetrics:
    metrics = RealtimeMetrics()
    tlv_3010 = find_first_tlv(payload, 0x3010, min_length=1)
    if tlv_3010 is not None:
        metrics.raw_0x3010_hex = tlv_3010[1].hex(" ")
    tlv_3020 = find_first_tlv(payload, 0x3020, expected_lengths={0x0C}, min_length=0x0C)
    if tlv_3020 is not None:
        _, value = tlv_3020
        metrics.raw_0x3020_hex = value.hex(" ")
        parse_0x3020_battery_metrics(value, metrics)
    tlv_3030 = find_0x3030_tlv(payload)
    if tlv_3030 is not None:
        _, value = tlv_3030
        parse_0x3030_power_metrics(value, metrics)
    tlv_3050 = find_first_tlv(payload, 0x3050, min_length=1)
    if tlv_3050 is not None:
        metrics.raw_0x3050_hex = tlv_3050[1].hex(" ")
    return metrics


