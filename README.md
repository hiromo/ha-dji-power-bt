# DJI Power Bluetooth for Home Assistant

DJI Power Bluetooth is a community-maintained custom integration that monitors
and controls DJI Power stations over local Bluetooth Low Energy (BLE).

> This is an unofficial community project. It is not affiliated with or
> endorsed by DJI.

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hiromo&repository=ha-dji-power-bt&category=integration)

## Supported devices

The following models have been tested with real hardware:

- DJI Power 2000
- DJI Power 1000 Mini

DJI Power 1000 and DJI Power 1000 V2 can be discovered by their known model
codes, but their model-specific configuration tables have not been fully
validated. The integration therefore exposes a conservative subset of entities
on those models. Unknown model codes receive the same conservative treatment.

Private development began in early June 2026. Power 2000 and Power 1000 Mini
have since undergone sustained testing in real Home Assistant environments,
including simultaneous multi-station connections, reconnect recovery,
telemetry, and configuration writes.

The integration is considered beta-quality and is intended for regular use
with verified devices. Because the BLE protocol is reverse engineered, support
for other models remains conservative, and future firmware changes may require
updates to the integration.

## Requirements and Bluetooth connection model

- Home Assistant with a local Bluetooth adapter or an ESPHome Bluetooth Proxy
  close enough to the station.
- One free BLE GATT connection slot per enabled DJI Power config entry.
- The station's 32-character hexadecimal local pair key.

Each connected station with BLE enabled occupies one persistent BLE GATT
connection and receives telemetry approximately once per second. Every
realtime packet is received and parsed; Home Assistant state publication is
throttled to five seconds by default and can be configured from 1 to 60
seconds.

A DJI Power station accepts only one BLE central connection at a time. This
integration cannot connect while DJI Home already holds the Bluetooth
connection to that same station. Disconnect DJI Home's Bluetooth session, or
close the app if it is using Bluetooth, before starting setup or allowing Home
Assistant to reconnect. DJI Home access over Wi-Fi or the DJI cloud does not
occupy the station's BLE connection and can remain active while this integration
is connected.

Each station also consumes one connection slot on the local Bluetooth adapter
or ESPHome Bluetooth Proxy. Make sure the adapter or proxy has enough capacity
for DJI Power plus every other connected BLE device. Simultaneous persistent
connections to multiple DJI Power stations have been verified with real
hardware; each station still consumes its own GATT slot.

## Installation

### HACS (recommended)

HACS must already be installed.

1. Use the button above, or open HACS and select **Custom repositories** from
   the top-right menu.
2. Add `https://github.com/hiromo/ha-dji-power-bt` as an
   **Integration**.
3. Download **DJI Power Bluetooth**.
4. Restart Home Assistant.
5. Open **Settings -> Devices & services -> Add integration** and select
   **DJI Power Bluetooth**.

Install future versions from the HACS update screen and restart Home Assistant
after updating the integration.

### Manual installation

Copy this directory into the Home Assistant configuration directory:

```text
/config/custom_components/dji_power_bt/
```

Restart Home Assistant, then add **DJI Power Bluetooth** from
**Settings -> Devices & services -> Add integration**.

## Initial setup and pair-key acquisition

The setup flow lists unconfigured, connectable advertisements containing DJI
manufacturer data (`0x08AA`). It determines the model automatically; users do
not type a BLE address or model name.

The flow offers three ways to obtain the per-device local pair key:

1. Sign in to a DJI account and retrieve it through the unofficial DJI Home
   private API flow.
2. Use an already acquired DJI member token.
3. Enter a known 32-character hexadecimal pair key manually.

The account and member-token methods exist for convenience during setup only.
Normal operation is local BLE. DJI may change its private endpoints at any
time, so these acquisition methods may stop working without notice. Account
email, password, CAPTCHA data, and member token are not stored in the config
entry.

If a setup form is reopened at the previously selected authentication method,
enable **Change authentication method** and submit the form to return to the
method menu.

## Pair-key storage and security

The pair key is a device authentication secret. The integration intentionally
does not display it in the GUI, downloaded diagnostics, logs, or protocol
captures. Authentication command `0x6A`, which carries the key, is excluded
from the capture feature.

Home Assistant must retain the key for future local authentication. It is
stored as `data.local_auth_key` in the config entry for domain
`dji_power_bt`. A Home Assistant administrator who needs to recover a
known key can inspect `/config/.storage/core.config_entries` from the host and
locate that config entry. Treat the file as read-only: do not edit Home
Assistant `.storage` files manually.

Displaying this field reveals the full key. Never paste it into an issue,
diagnostic bundle, screenshot, public capture, or chat. Protect the Home
Assistant host and backups because they contain the key. If cloud acquisition
still works, storing the key separately in an encrypted password manager or
secret vault can preserve a recovery path if DJI later changes the private API.

As a last-resort recovery method for a station you own, the key can also be
identified by capturing and analyzing the BLE authentication exchange between
DJI Home and the station: the second command `0x6A` request contains the
32 ASCII hexadecimal key bytes. Such captures contain authentication secrets;
keep them private, use them only on devices and traffic you are authorized to
inspect, and delete or encrypt the raw capture after recovery.

## Main features

- Battery state of charge, remaining time, battery temperature, firmware, and
  total input/output telemetry.
- AC inlet/outlet, USB, SDC, 12 V, and XT60 telemetry where supported and
  reported by the device.
- Charge and discharge limits.
- AC output control and model-specific SDC control.
- Power 2000 scheduled-energy controls and complete tariff-schedule writes.
- Power 1000 Mini charging-mode selection.
- Sanitized Home Assistant diagnostics and bounded protocol capture that
  excludes authentication traffic.

Model capability and current device mode are checked separately. A control can
remain unavailable even when the entity exists if the active mode does not
support that operation.

## Power 2000 energy management

### Supported Energy Saver mode

The integration supports DJI Home's **Disabled** and **Scheduled periods**
Energy Saver modes. Home Assistant exposes these as Energy optimization mode
values `disabled` and `scheduled`.

**Grid-Tied ESS is not supported.** The integration does not implement
Grid-Tied ESS reads or writes and blocks Scheduled-oriented `0x1018` controls
when the station reports an unknown or unsupported energy optimization mode.
Use DJI Home to leave Grid-Tied ESS before controlling Scheduled settings from
Home Assistant.

### Verified Scheduled-period behavior

The following behavior has been verified on Power 2000 hardware while Energy
optimization mode is `scheduled`. It is station firmware behavior; Home
Assistant configures the relevant values but does not emulate the power-flow
logic.

1. When `SoC <= Discharge limit + 5%`, the station forces bypass supply while
   AC input is available. This protection rule takes priority over every rule
   below.
2. When **Off-peak charging** is off, the station does not charge its battery
   from AC.
3. **Off-peak charging power** acts as the maximum AC input power. During bypass,
   if the connected load needs more power than this limit, the battery supplies
   the shortfall, subject to the protection rule above.
4. When **Tariff period** is `peak` and **Peak discharging** is on, Power 2000
   stops AC input by itself. An external smart plug on the AC inlet is not
   required. If SoC falls to `Discharge limit + 5%` or below, the station
   automatically resumes AC input to preserve forced bypass supply.

Firmware can change device behavior. Validate the resulting power flow on your
own installation before using these controls for unattended high-power loads.

### All-day tariff preset buttons

Power 2000 provides two configuration-category buttons:

- **Set all-day off-peak tariff**
- **Set all-day peak tariff**

Both entities are disabled by default. They are convenience wrappers around
`dji_power_bt.set_tariff_schedule`; enable one in the Home Assistant entity
registry only when a manual dashboard button is useful. Automations should call
the action directly.

Pressing either button completely replaces the station's DJI Home
**Electricity price time period** table with the selected all-day profile. It
does not merge with an existing timetable. Any detailed weekday or time-of-day
schedule previously created in DJI Home is overwritten.

The preset writes two everyday slots (`00:00-23:59` and `23:59-00:00`) because
the first range alone does not include the 23:59 minute on verified Power 2000
firmware.

### Tariff schedule action

`dji_power_bt.set_tariff_schedule` completely replaces the Power 2000 tariff
table. Supply either an all-day `preset` or a complete `periods` list, never
both. For example:

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

Times have minute precision. A period ending earlier than it starts crosses
midnight. Overlaps and equal start/end times are rejected, while uncovered
times are allowed. Detailed period writes are based on the observed tariff
record layout but have not yet been validated on real hardware; the two all-day
presets have been validated on Power 2000.

### Combined scheduled-energy service

`dji_power_bt.set_scheduled_energy_settings` updates one or more of the
following Power 2000 settings in one safe `0x1018` read-modify-write operation:

| Field | Value |
|---|---|
| `energy_optimization_mode` | `disabled` or `scheduled` |
| `peak_discharging` | `true` or `false` |
| `off_peak_charging` | `true` or `false` |
| `off_peak_charging_power` | watts within the device-reported range |

At least one field is required. Unspecified fields retain their current
device-reported bytes, and no BLE write is sent when all requested values
already match.

Use this service in automations instead of issuing several separate select,
switch, and number actions. It applies related settings in a single serialized
transaction, avoids unnecessary BLE traffic, and avoids exposing intermediate
combinations of settings while an automation is running.

Example:

```yaml
action: dji_power_bt.set_scheduled_energy_settings
data:
  device_id: <Power 2000 device ID>
  energy_optimization_mode: scheduled
  peak_discharging: false
  off_peak_charging: true
  off_peak_charging_power: 800
```

The tariff timetable is stored in separate `0x1016/0x1017` records and cannot
be changed in the same transaction as
`set_scheduled_energy_settings` (`0x1018`). To set an all-day tariff and the
scheduled-energy fields, call the two actions sequentially:

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

Power 1000 Mini exposes a **Charging mode** select based on the mode table
reported by the station. Verified options are `slow` (nominal 500 W) and `fast`
(nominal 1,000 W). The integration preserves the complete reported table when
changing the selected mode.

## Bluetooth troubleshooting

### No device appears during setup

The setup list intentionally requires a connectable advertisement containing
DJI manufacturer data with company ID `0x08AA`. A station can temporarily emit
a name-only advertisement without manufacturer data; that packet is not enough
for safe model detection and is not listed.

Make sure DJI Home is not holding a Bluetooth connection to the station, keep
the station and adapter/proxy nearby, wait for a later advertisement containing
manufacturer data, and retry setup. In observed cases, the manufacturer-data
advertisement appeared after waiting. DJI Home may remain in use over Wi-Fi or
the DJI cloud; only avoid initiating a DJI Home Bluetooth connection to that
station while Home Assistant is discovering or connecting.

### Unstable connection or reconnect delay

After an unexpected disconnect, the integration waits five seconds, discards
the pre-disconnect BLE device object, and requires a fresh connectable
advertisement before reconnecting. Recoverable failures then use outer backoff
delays of **10, 30, 60, 120, and 300 seconds**. A successful authenticated and
initialized connection resets the backoff.

This conservative schedule prevents rapid connection churn and stale-client
reuse. A reconnect can therefore take several minutes after repeated failures.
Check RF coverage, make sure DJI Home is not holding the station's Bluetooth
connection, and confirm that the Bluetooth adapter or ESPHome proxy still has a
free connection slot before assuming the integration has stopped retrying.
DJI Home Wi-Fi and cloud access do not need to be disabled.

## Diagnostics and protocol capture

Home Assistant diagnostics include connection phases, reconnect counters,
failure categories, GATT lifecycle state, write verification, and safe protocol
details. Identifiers are redacted where appropriate, and pair keys, member
tokens, passwords, CAPTCHA data, and command `0x6A` payloads are excluded.

The disabled-by-default **Capture protocol payloads** diagnostic button records
a bounded in-memory sample. The
`dji_power_bt.start_protocol_capture` action provides explicit duration
and frame-count limits. Captures are exposed only through Home Assistant
diagnostics and are not continuously written to disk.

## Known limitations

- Grid-Tied ESS is unsupported.
- DJI account and member-token setup depend on private DJI endpoints and may
  stop working after a DJI-side change.
- Power 1000 and Power 1000 V2 have not received the same model-specific
  hardware validation as Power 2000 and Power 1000 Mini.
- Unknown or incomplete nested configuration tables are read conservatively;
  writes are refused rather than risking deletion of unknown records.
- A station whose BLE connection is currently occupied by DJI Home is
  unavailable to this integration. DJI Home Wi-Fi and cloud connections can
  remain active concurrently.
- Pair keys are stored in Home Assistant config entries, so the host and backups
  must be protected.

## License

DJI Power Bluetooth is licensed under the
[Apache License 2.0](LICENSE), the same license used by Home Assistant Core.
DJI names and product marks remain the property of their respective owners; the
license does not grant trademark rights.

Copyright 2026 hiromo and contributors.

## Documentation and release history

- [Public changelog](CHANGELOG.md)
- [GitHub Releases](https://github.com/hiromo/ha-dji-power-bt/releases)
- [Engineering documentation](docs/README.md)
- [Detailed development history](docs/release-history.md)

Current engineering behavior is documented by topic under `docs/`. Historical
release notes describe superseded behavior and are not a second current
specification.
