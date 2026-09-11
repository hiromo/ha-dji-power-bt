# DJI Power Bluetooth for Home Assistant

DJI Power Bluetooth is an unofficial, community-maintained custom integration
for monitoring and controlling DJI Power stations over local Bluetooth Low
Energy (BLE). It is not affiliated with or endorsed by DJI.

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hiromo&repository=ha-dji-power-bt&category=integration)

## Supported devices

Real-hardware testing covers:

- DJI Power 2000
- DJI Power 1000 Mini

DJI Power 1000 and 1000 V2 are discoverable by known model codes but expose a
conservative entity subset because their configuration tables are not fully
validated. Unknown models use the same policy.

Private development began in early June 2026. Power 2000 and Power 1000 Mini
have since received sustained Home Assistant testing, including simultaneous
connections, reconnects, telemetry, and configuration writes. The integration
is beta-quality and intended for regular use with verified devices. Its
reverse-engineered protocol and unverified models may require changes after DJI
firmware updates.

## Requirements and connection model

- Home Assistant with a nearby local Bluetooth adapter or ESPHome Bluetooth
  Proxy.
- At least one connection slot per enabled DJI Power config entry.
- The station's 32-character hexadecimal local pair key.

Each enabled station uses one persistent BLE GATT connection and sends telemetry
approximately once per second. Every realtime packet is parsed; Home Assistant
publishes state every five seconds by default, configurable from 1 to 60 seconds.
Simultaneous persistent connections to multiple DJI Power stations are verified,
provided the adapter or proxy has one free GATT slot per station and enough
capacity for its other BLE devices.

A station accepts only one BLE central. DJI Home cannot hold a Bluetooth
connection to the same station while this integration connects; end that
Bluetooth session or close the app before setup or reconnect. DJI Home access
over Wi-Fi or the DJI cloud does not occupy the station's BLE connection and may
remain active.

## Installation

### HACS (recommended)

HACS must already be installed.

1. Use the button above, or add
   `https://github.com/hiromo/ha-dji-power-bt` to HACS **Custom repositories**
   as an **Integration**.
2. Download **DJI Power Bluetooth** and restart Home Assistant.
3. Open **Settings -> Devices & services -> Add integration** and select
   **DJI Power Bluetooth**.

Install updates from HACS and restart Home Assistant afterward.

### Manual installation

Copy the integration to `/config/custom_components/dji_power_bt/`, restart Home
Assistant, then add **DJI Power Bluetooth** from **Settings -> Devices &
services -> Add integration**.

## Initial setup and pair key

Setup lists unconfigured, connectable advertisements containing DJI manufacturer
data (`0x08AA`) and derives the model automatically; no BLE address or model name
is entered manually. Obtain the device's local pair key by:

1. Signing in to a DJI account through the unofficial DJI Home private API flow.
2. Using an existing DJI member token.
3. Entering a known 32-character hexadecimal pair key.

Account and token lookup are setup conveniences and may break if DJI changes its
private endpoints. Account email, password, CAPTCHA data, and member token are
not stored. If setup reopens at the previous authentication form, enable
**Change authentication method** and submit it to return to the method menu.

### Storage and recovery

The pair key is a secret. It is hidden from the GUI, diagnostics, logs, and
protocol captures; authentication command `0x6A` is excluded from capture.
Home Assistant stores the key as `data.local_auth_key` in the `dji_power_bt`
entry under `/config/.storage/core.config_entries`. Administrators may inspect
that file read-only to recover a known key; never edit `.storage` manually.

Protect the Home Assistant host and backups, and never paste the key into an
issue, diagnostic bundle, screenshot, capture, or chat. An encrypted password
manager or secret vault provides a recovery copy if DJI cloud lookup later stops
working.

For a station you own, a last-resort recovery method is capturing and analyzing
the BLE authentication exchange in an Android Bluetooth HCI snoop log. Disable
mobile data and Wi-Fi, leave Bluetooth enabled, and connect with DJI Home while
recording; the second `0x6A` request contains the 32 ASCII hexadecimal key bytes.
Bug reports and HCI logs can also contain device identifiers, unrelated nearby
traffic, and other secrets. Inspect only authorized traffic, keep the files
private, and encrypt or delete them after recovery.

## Main features

- Battery state of charge, remaining time, temperature, firmware, and total
  input/output telemetry.
- AC inlet/outlet, USB, SDC, 12 V, and XT60 telemetry when reported.
- Charge/discharge limits, AC output, and model-specific SDC controls.
- Power 2000 scheduled-energy and complete tariff-schedule controls.
- Power 1000 Mini charging-mode selection.
- Sanitized diagnostics and bounded protocol capture without authentication
  traffic.

Capabilities and the current device mode are checked separately, so an existing
entity may be unavailable when its operation is invalid in the active mode.

## Power 2000 energy management

### Supported Energy Saver mode

DJI Home's **Disabled** and **Scheduled periods** modes appear as `disabled` and
`scheduled`. **Grid-Tied ESS is not supported**: the integration neither reads
nor writes it and blocks Scheduled-oriented `0x1018` controls for unknown or
unsupported modes. Leave Grid-Tied ESS in DJI Home before using those controls.

### Verified Scheduled-period behavior

On verified Power 2000 firmware in `scheduled` mode:

1. With AC available, `SoC <= Discharge limit + 5%` forces bypass supply and
   overrides the following rules.
2. Disabling **Off-peak charging** prevents battery charging from AC.
3. **Off-peak charging power** limits total AC input; during bypass the battery
   supplies load above that limit, subject to rule 1.
4. During a `peak` **Tariff period**, enabling **Peak discharging** stops AC
   input without an external smart plug. AC input resumes at the rule 1 limit.

Firmware may change this behavior. Validate power flow before unattended,
high-power use.

### Tariff schedule

The **Set all-day off-peak tariff** and **Set all-day peak tariff** buttons call
`dji_power_bt.set_tariff_schedule`. Both entities are disabled by default;
enable them only when a dashboard button is useful. Automations should call the
action directly. Either button completely replaces DJI Home's **Electricity
price time period** table, including detailed schedules, with two everyday
slots: `00:00-23:59` and `23:59-00:00`. The second covers the otherwise omitted
23:59 minute.

The action accepts either an all-day `preset` or a complete `periods` list:

```yaml
action: dji_power_bt.set_tariff_schedule
data:
  device_id: <Power 2000 device ID>
  periods:
    - tariff: off_peak
      weekdays: [mon, tue, wed, thu, fri]
      start_time: "00:00"
      end_time: "07:00"
    - tariff: peak
      weekdays: [mon, tue, wed, thu, fri]
      start_time: "07:00"
      end_time: "23:59"
```

Times have minute precision. An end before its start crosses midnight; overlaps
and equal endpoints are rejected, while gaps are allowed. Detailed period writes
use an observed record layout and lack real-hardware validation; the all-day
presets are verified on Power 2000.

### Combined scheduled-energy action

`dji_power_bt.set_scheduled_energy_settings` changes one or more fields in one
serialized `0x1018` read-modify-write operation:

| Field | Value |
|---|---|
| `energy_optimization_mode` | `disabled` or `scheduled` |
| `peak_discharging` | `true` or `false` |
| `off_peak_charging` | `true` or `false` |
| `off_peak_charging_power` | device-reported watt range |

At least one field is required. Unspecified device bytes are preserved, and a
request matching the current value sends no BLE write. This avoids separate
entity calls and intermediate setting combinations.

```yaml
action: dji_power_bt.set_scheduled_energy_settings
data:
  device_id: <Power 2000 device ID>
  energy_optimization_mode: scheduled
  peak_discharging: false
  off_peak_charging: true
  off_peak_charging_power: 800
```

Tariffs use separate `0x1016/0x1017` records, so call the tariff and scheduled
actions sequentially when changing both:

```yaml
- action: dji_power_bt.set_tariff_schedule
  data:
    device_id: <Power 2000 device ID>
    preset: all_day_off_peak

- action: dji_power_bt.set_scheduled_energy_settings
  data:
    device_id: <Power 2000 device ID>
    energy_optimization_mode: scheduled
    peak_discharging: false
    off_peak_charging: true
    off_peak_charging_power: 800
```

## Power 1000 Mini charging mode

The station-reported **Charging mode** table supplies `slow` (nominal 500 W) and
`fast` (nominal 1,000 W) on verified hardware. Changing the selected mode
preserves the complete table.

## Bluetooth troubleshooting

### Device missing during setup

Discovery requires a connectable advertisement with `0x08AA` manufacturer data;
a temporary name-only advertisement cannot identify the model. Ensure DJI Home
does not hold Bluetooth, keep the station near the adapter/proxy, wait 3-5
minutes for another advertisement, and retry. DJI Home Wi-Fi/cloud use may
continue.

### Unstable connection or delayed reconnect

After an unexpected disconnect, the integration waits five seconds, discards
the old BLE device object, and requires a fresh connectable advertisement.
Recoverable failures then wait **10, 30, 60, 120, and 300 seconds**; a successful
authenticated initialization resets that backoff. Check RF coverage, DJI Home
Bluetooth use, and free adapter/proxy slots before assuming retries have stopped.

## Diagnostics and protocol capture

Home Assistant diagnostics contain connection phases, reconnect and failure
counters, GATT lifecycle state, write verification, and safe protocol metadata.
Identifiers are redacted where appropriate; pair keys, member tokens, passwords,
CAPTCHA data, and `0x6A` payloads are excluded.

The disabled-by-default **Capture protocol payloads** button records a bounded
in-memory sample. `dji_power_bt.start_protocol_capture` adds explicit duration
and frame limits. Captures are available only through diagnostics and are not
continuously written to disk.

## Known limitations

- Grid-Tied ESS remains unsupported.
- Private DJI account/token endpoints may change.
- Power 1000, Power 1000 V2, and unknown models use conservative support.
- Incomplete nested configuration tables are not written.
- DJI Home Bluetooth and this integration cannot share one station connection.
- Pair keys in config entries require protected hosts and backups.

## License and documentation

[Apache License 2.0](LICENSE), matching Home Assistant Core. DJI names and marks
belong to their owners; the license grants no trademark rights. Copyright 2026
hiromo and contributors.

- [Public changelog](CHANGELOG.md)
- [GitHub Releases](https://github.com/hiromo/ha-dji-power-bt/releases)
- [Engineering documentation](docs/README.md)
- [Detailed development history](docs/release-history.md)

Topical documents define current behavior; release history records superseded
implementation details.
