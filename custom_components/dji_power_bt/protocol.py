"""Compatibility facade for the split DJI Power BLE protocol modules.

Protocol implementation is intentionally split by responsibility. Existing
imports from ``.protocol`` remain supported so entity/platform code and third-
party tests do not need to follow internal file layout.
"""
from __future__ import annotations

from .protocol_common import (
    GROUP_TYPE_NAMES, INTERFACE_TYPE_NAMES, normalize_address, u16le, u32le,
    validate_local_auth_key,
)
from .protocol_discovery import AdvertisementInfo, parse_manufacturer_data
from .protocol_frame import (
    DumlFrame, DumlReassembler, build_duml_frame, crc16_dji, crc8_dji,
    duml_length_from_header, find_first_tlv, find_tlvs, iter_tlvs,
    parse_duml_frame,
)
from .protocol_hms import (
    HmsRecord, HmsReport, parse_0x66_hms, reuse_0x66_hms_report,
    split_0x66_hms_payload, update_hms_pattern_history,
)
from .protocol_config import (
    DEFAULT_STATUS_REQUEST_PAYLOAD, ChargingModeOption, OutputInterfaceState,
    MAX_TARIFF_SLOTS,
    PowerConfig, TARIFF_SCHEDULE_PROFILE_ALL_DAY_OFF_PEAK,
    TARIFF_SCHEDULE_PROFILE_ALL_DAY_PEAK, TARIFF_SCHEDULE_PROFILE_OPTIONS,
    TARIFF_SCHEDULE_PROFILE_OTHER, TARIFF_PRESET_OPTIONS, TARIFF_WEEKDAY_BITS,
    TariffSlot, build_0x63_1005_payload_from_config,
    build_0x63_charging_mode_payload_from_config, build_0x63_output_payload_from_config,
    build_0x63_payload_from_config, build_0x63_tariff_payload,
    build_0x63_tariff_schedule_payload, build_keyed_header,
    classify_tariff_schedule, decode_day_mask, decode_day_mask_ja,
    make_0x1005_write_tlv, make_0x100d_output_table_write_tlv,
    make_0x100e_command_write_tlv, make_0x1016_tariff_table_write_tlv,
    make_0x1018_write_tlv, make_0x101e_charging_mode_write_tlv,
    make_all_day_tariff_slot, make_all_day_tariff_slots, make_simple_write_tlv,
    make_tariff_slots_from_periods, make_tariff_slots_from_preset,
    parse_0x100d_output_states, parse_0x1017_time_slot, parse_0x1018_unknown_power_block,
    parse_0x101e_charging_modes, parse_0x63_write_result, parse_power_config,
    update_0x1005_charge_limit, update_0x1005_discharge_limit,
    update_0x1018_energy_optimization_mode, update_0x1018_off_peak_charge_enabled,
    update_0x1018_off_peak_power, update_0x1018_peak_discharge_enabled,
    tariff_schedule_signature, validate_tariff_slots, write_result_ok,
)
from .protocol_realtime import (
    RealtimeMetrics, find_0x3030_tlv, parse_0x3020_battery_metrics,
    parse_0x3030_power_metrics, parse_realtime_metrics,
)

__all__ = [name for name in globals() if not name.startswith("_")]
