"""Constants for the DJI Power Bluetooth custom integration."""
from __future__ import annotations

DOMAIN = "dji_power_bt"

CONF_LOCAL_AUTH_KEY = "local_auth_key"
CONF_ADDRESS = "address"
CONF_DEVICE_NAME = "device_name"
CONF_MODEL = "model"
CONF_MODEL_CODE = "model_code"
CONF_SERIAL_NUMBER = "serial_number"
CONF_SCAN_TIMEOUT = "scan_timeout"
CONF_TELEMETRY_UPDATE_INTERVAL = "telemetry_update_interval"
CONF_DEVICE = "device"
CONF_MEMBER_TOKEN = "member_token"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_CAPTCHA_CODE = "captcha_code"

DEFAULT_SCAN_TIMEOUT = 10.0
DEFAULT_TELEMETRY_UPDATE_INTERVAL = 5
MIN_TELEMETRY_UPDATE_INTERVAL = 1
MAX_TELEMETRY_UPDATE_INTERVAL = 60

DJI_COMPANY_ID = 0x08AA
KNOWN_MODEL_CODES = frozenset({0x91, 0x94, 0x97, 0x98})
MODEL_NAMES: dict[int, str] = {
    0x91: "DJI Power 1000",
    0x94: "DJI Power 2000",
    0x97: "DJI Power 1000 V2",
    0x98: "DJI Power 1000 Mini",
}

CHAR_WRITE_C304 = "0000c304-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY_C305 = "0000c305-0000-1000-8000-00805f9b34fb"

PLATFORMS = ["sensor", "number", "switch", "select", "binary_sensor", "button"]


SERVICE_START_PROTOCOL_CAPTURE = "start_protocol_capture"
SERVICE_SET_SCHEDULED_ENERGY_SETTINGS = "set_scheduled_energy_settings"
SERVICE_SET_TARIFF_SCHEDULE = "set_tariff_schedule"
ATTR_DEVICE_ID = "device_id"
ATTR_ENERGY_OPTIMIZATION_MODE = "energy_optimization_mode"
ATTR_PEAK_DISCHARGING = "peak_discharging"
ATTR_OFF_PEAK_CHARGING = "off_peak_charging"
ATTR_OFF_PEAK_CHARGING_POWER = "off_peak_charging_power"
ATTR_DURATION_SECONDS = "duration_seconds"
ATTR_MAX_FRAMES = "max_frames"
ATTR_PRESET = "preset"
ATTR_PERIODS = "periods"
ATTR_TARIFF = "tariff"
ATTR_WEEKDAYS = "weekdays"
ATTR_START_TIME = "start_time"
ATTR_END_TIME = "end_time"

DEFAULT_CAPTURE_DURATION_SECONDS = 30
DEFAULT_CAPTURE_MAX_FRAMES = 100
SAFE_PAYLOAD_COMMANDS = frozenset({0x60, 0x61, 0x62, 0x63, 0x66})
