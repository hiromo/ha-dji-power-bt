"""Model and runtime capability hints for DJI Power devices."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .const import MODEL_NAMES


class RuntimeFeature(StrEnum):
    """Features whose current availability depends on the active device mode."""

    OFF_PEAK_CHARGING = "off_peak_charging"
    PEAK_DISCHARGING = "peak_discharging"
    OFF_PEAK_CHARGING_POWER = "off_peak_charging_power"
    TARIFF_PERIOD = "tariff_period"
    TARIFF_TIME_SLOTS = "tariff_time_slots"


@dataclass(frozen=True, slots=True)
class DjiPowerCapabilities:
    """Capabilities used to decide which entities are created."""

    usb_a_ports: int = 0
    usb_c_ports: int = 0
    usb_c_input: bool = False
    sdc_ports: int = 0
    has_sdc: bool = False
    has_sdc_lite: bool = False
    has_12v_accessory: bool = False
    has_xt60_accessory: bool = False
    has_tariff_slots: bool = False
    has_off_peak_charging: bool = False
    off_peak_charging_power_step_w: int | None = None
    has_peak_discharging: bool = False
    has_charge_limits: bool = True
    has_ac_output: bool = True
    has_sdc_control: bool = False
    has_charging_mode: bool = False
    has_energy_optimization: bool = False


_CAPABILITIES_BY_MODEL_CODE: dict[int, DjiPowerCapabilities] = {
    # DJI official port counts: USB-A x2, USB-C x2, SDC x1, SDC Lite x1.
    0x91: DjiPowerCapabilities(
        usb_a_ports=2,
        usb_c_ports=2,
        sdc_ports=1,
        has_sdc=True,
        has_sdc_lite=True,
        has_12v_accessory=True,
        has_xt60_accessory=True,
    ),
    # Power 2000 exposes scheduled energy optimisation and tariff settings.
    0x94: DjiPowerCapabilities(
        usb_a_ports=4,
        usb_c_ports=4,
        sdc_ports=2,
        has_sdc=True,
        has_12v_accessory=True,
        has_xt60_accessory=True,
        has_tariff_slots=True,
        has_off_peak_charging=True,
        # Confirmed on Power 2000. 0x1018 offset 34 currently also reports
        # 10, but that field remains diagnostic-only until its semantics are
        # confirmed across additional models.
        off_peak_charging_power_step_w=10,
        has_peak_discharging=True,
        has_energy_optimization=True,
    ),
    # DJI official port counts: USB-A x2, USB-C x2, SDC x1, SDC Lite x1.
    0x97: DjiPowerCapabilities(
        usb_a_ports=2,
        usb_c_ports=2,
        sdc_ports=1,
        has_sdc=True,
        has_sdc_lite=True,
        has_12v_accessory=True,
        has_xt60_accessory=True,
    ),
    # Verified from Android DJI Home BLE captures. 0x100D contains AC, USB and
    # SDC interface records, and 0x101E contains slow/fast charging-mode records.
    0x98: DjiPowerCapabilities(
        usb_a_ports=2,
        usb_c_ports=2,
        usb_c_input=True,
        sdc_ports=1,
        has_sdc=True,
        has_12v_accessory=True,
        has_xt60_accessory=True,
        has_sdc_control=True,
        has_charging_mode=True,
    ),
}


def capabilities_for_model_code(model_code: int | None) -> DjiPowerCapabilities:
    """Return conservative capabilities for an advertisement model code."""
    if model_code is None:
        return DjiPowerCapabilities()
    return _CAPABILITIES_BY_MODEL_CODE.get(model_code, DjiPowerCapabilities())


def model_name_for_code(model_code: int | None) -> str:
    """Return a stable human-readable model name."""
    if model_code is None:
        return "DJI Power"
    return MODEL_NAMES.get(model_code, f"DJI Power (0x{model_code:02X})")


def infer_model_code(model: str | None) -> int | None:
    """Migrate old free-text model values to advertisement model codes."""
    normalized = " ".join((model or "").casefold().replace("-", " ").replace("_", " ").split())
    if "1000 mini" in normalized or "dym1000m" in normalized:
        return 0x98
    if "1000 v2" in normalized:
        return 0x97
    if "2000" in normalized or "dym2000" in normalized:
        return 0x94
    if "1000" in normalized or "dym1000" in normalized:
        return 0x91
    return None
