# Home Assistant integration surface

## Config entry

`DjiPowerConfigFlow.VERSION = 1` is the first public compatibility baseline.

The first public integration domain is `dji_power_bt`, matching the
`custom_components/dji_power_bt` directory and `manifest.json`. The pre-public
`dji_power` and `dji_power_bluetooth` domains are retired and have no in-place
migration. Home Assistant treats each domain as a different integration, so a
development installation must remove the old entry and register the device
again.

Pre-public config-entry versions `2` through `8` and their migration handler were
retired before publication. They are development history, not supported upgrade
sources. An existing development installation with one of those entries must
remove and recreate the DJI Power Bluetooth config entry.

The config-entry version is independent of both the config entry's Bluetooth
address unique ID and entity unique IDs. Current entity unique IDs continue to
use the normalized BLE address plus the current entity key.

After the first public release, treat config-entry fields, the config-entry
version, and entity unique IDs as compatibility surfaces. Any later incompatible
change requires an explicit migration and release-contract coverage.

Stored runtime-critical data includes the normalized device BLE address, model/model code, device name, local pair key, and optional serial number. Setup-only account credentials/member tokens are not persisted.

The pair key is intentionally absent from GUI surfaces and exported diagnostics.
An administrator can recover a known stored key by inspecting the matching
`dji_power_bt` entry's `data.local_auth_key` field in
`/config/.storage/core.config_entries`. This is a read-only recovery procedure;
users must not edit `.storage` files manually. See
`docs/protocol/authentication.md` for the full secret-handling boundary.

The normal user step lists candidates from Home Assistant Bluetooth discovery
using DJI manufacturer data (`0x08AA`) and derives the model code from the
advertisement; it does not ask for a manually typed BLE address or model name.
Authentication setup then offers DJI account lookup, existing member-token
lookup, or direct entry of a known 32-character hexadecimal pair key.

Home Assistant keeps a Bluetooth-discovery config flow on the server at its
current step. Reopening that discovery opens the existing flow ID, and closing
the frontend dialog does not invoke an integration callback that could reset or
abort it. The last authentication form can therefore reappear after the dialog
is closed; this is config-flow state, not a per-device preference or config-entry
data.

Every setup form after the authentication-method menu provides a
`change_auth_method` checkbox. Submitting a form with this checkbox enabled
clears setup-only cloud credentials and returns the same flow to the
authentication-method menu. Credential fields are validated by the flow rather
than by frontend-required markers so this return action can be submitted without
entering credentials. The integration cannot automatically detect the dialog's
close button, so merely closing and reopening still resumes the current form;
the explicit return action is the supported recovery path.

### Resetting a pre-public development installation

Before replacing version 8 code with the public version 1 baseline:

1. Create a Home Assistant backup.
2. Confirm that the device can be registered again using a known local pair key,
   DJI account lookup, or an existing member token.
3. In **Settings -> Devices & services -> DJI Power Bluetooth**, delete each
   development config entry while the old integration is still installed.
4. Remove `/config/custom_components/dji_power` and
   `/config/custom_components/dji_power_bluetooth`, install the version 1 files
   as `/config/custom_components/dji_power_bt`, and restart Home Assistant.
5. Add each DJI Power device again through Bluetooth discovery and verify entity
   IDs used by dashboards and automations.

Do not edit `.storage/core.config_entries` to force the stored version from `8`
to `1` or its domain from `dji_power` or `dji_power_bluetooth` to
`dji_power_bt`. Do not leave retired and current component directories
installed together. If the new integration was installed before the old entry
was removed, restore the previous integration files if necessary, restart,
remove the old entry through the UI, then reinstall the new domain.

## Platforms

Current platforms:

```text
sensor
number
switch
select
binary_sensor
button
```

`entry.runtime_data` is the `DjiPowerManager` shared by these platforms.

## Availability principles

Most data/control entities require a connected and authenticated manager plus a meaningful current value or runtime feature availability.

The BLE switch remains available while disconnected so a user can re-enable BLE.

The BLE connectivity binary sensor remains available as a diagnostic connectivity surface and reports connected + authenticated state.

Missing per-port telemetry is not converted to zero. If a port has not been reported, its value can remain unknown while the device itself is connected.

## Main sensors

Common user-facing sensors include:

- SoC
- total input power
- total output power
- AC input power (`ac_inlet_input_power_w`)
- AC output power (`ac_outlet_output_power_w`)
- USB output power
- SDC input/output when supported
- battery temperature
- remaining time
- firmware
- communication-module firmware

The usual entity mapping for confirmed AC directions is
`sensor.<device>_ac_input_power` from `ac_inlet_input_power_w` and
`sensor.<device>_ac_output_power` from `ac_outlet_output_power_w`.

Additional per-port, reverse-direction, battery-status/raw, XT60, SDC Lite, 12 V, last-notify, and protocol/diagnostic sensors may be disabled by default or remain diagnostic-only depending on confidence/support.

Do not expose `ac_inlet_output_power_w` or `ac_outlet_input_power_w` as normal entities until their semantics are confirmed.

USB-A and USB-C share one protocol aggregate. `usb_output_power` is the normal
aggregate entity. `usb_input_power` is enabled by default only for a capability
profile with confirmed USB-C input, currently Power 1000 Mini. Individual
USB-A/USB-C input/output entities are disabled by default. Missing port data is
unknown, a reported zero is `0 W`, and a disconnected manager makes the entity
unavailable.

Do not add separate USB-A and USB-C aggregate entities in parallel with the
protocol-group aggregate.

## Numbers

- `number.<device>_off_peak_charging_power`: Power 2000 capability; reported min/max with 10 W model step currently confirmed for Power 2000;
- charge limit;
- discharge limit.

## Switches

- off-peak charging where supported and runtime-available;
- peak discharging where supported and runtime-available;
- AC output;
- SDC where controllable;
- integration BLE enable/disable.

## Selects

- energy optimization mode on supported Power 2000 behavior;
- charging mode on supported models, currently verified on Power 1000 Mini using the device-reported 0x101E table.

## Buttons

Power 2000 tariff preset buttons are available for known supported tariff behavior:

- set all-day peak tariff;
- set all-day off-peak tariff.

Both buttons are configuration entities disabled by default. Each preset
replaces the complete device tariff table; it does not merge with a timetable
created in DJI Home. Enabling and pressing a preset therefore deliberately
overwrites DJI Home's Electricity price time period configuration.

The buttons are convenience wrappers around
`dji_power_bt.set_tariff_schedule` with `preset: all_day_peak` or
`preset: all_day_off_peak`. New automations should call the action directly;
the buttons remain available for manual dashboard use.

Each preset writes two everyday time slots, `00:00-23:59` and
`23:59-00:00`, because Power 2000 does not include the 23:59 minute in the
first range alone.

A protocol payload-capture diagnostic button exists but is disabled by default.

## Services

### `dji_power_bt.start_protocol_capture`

Fields:

- `device_id` required;
- `duration_seconds` optional, default 30, range 1-300;
- `max_frames` optional, default 100, range 1-1000.

Capture is memory-only/bounded. Sensitive authentication payloads are excluded.

### `dji_power_bt.set_scheduled_energy_settings`

Power 2000-oriented combined setting service. Optional fields:

- `energy_optimization_mode`: `disabled` or `scheduled`;
- `peak_discharging`: boolean;
- `off_peak_charging`: boolean;
- `off_peak_charging_power`: watts.

The manager validates compatible mode/capability and performs a safe 0x1018 read-modify-write.

At least one field is required. Fields not supplied by the caller keep the
device-reported value. If all requested values already match, no BLE write is
sent. When off-peak charging power is the only changed field, the service uses
the passive high-frequency verification policy; otherwise it uses the active
low-frequency policy. Tariff slots are separate 0x1016/0x1017 records and are
outside this service.

Automations should prefer this combined service when changing more than one
scheduled-energy field. A single serialized read-modify-write avoids multiple
BLE transactions and intermediate setting combinations while preserving every
unspecified byte. The separate tariff table must be changed with a tariff
schedule action as a preceding or following action; there is no atomic transaction that
combines `0x1016/0x1017` tariff slots with `0x1018` scheduled-energy fields.

Example:

```yaml
action: dji_power_bt.set_scheduled_energy_settings
data:
  device_id: <DJI Power device ID>
  energy_optimization_mode: scheduled
  peak_discharging: false
  off_peak_charging: true
  off_peak_charging_power: 800
```

### `dji_power_bt.set_tariff_schedule`

Power 2000 tariff-table replacement action. It requires `device_id` and
exactly one of these input forms:

- `preset`: `all_day_peak` or `all_day_off_peak`;
- `periods`: one or more complete period objects containing `tariff`
  (`peak` or `off_peak`), `weekdays` (`mon` through `sun`), `start_time`, and
  `end_time`.

The supplied schedule replaces the complete device tariff table; it is never
merged with the current table or the DJI Home timetable. Times use whole-minute
precision. An end time earlier than the start time crosses midnight. Equal
start and end times, duplicate weekdays, and overlapping periods are rejected;
gaps are allowed. The action accepts at most 64 periods, a transport-derived
limit rather than a confirmed Power 2000 UI/device limit.

Preset example:

```yaml
action: dji_power_bt.set_tariff_schedule
data:
  device_id: <DJI Power device ID>
  preset: all_day_off_peak
```

Detailed example:

```yaml
action: dji_power_bt.set_tariff_schedule
data:
  device_id: <DJI Power device ID>
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

The two preset payloads are confirmed on Power 2000. Detailed period writes
reuse the observed 0x1017 record layout inside the 0x1016 write table and are
currently an inferred implementation; they have not yet received real-device
validation.

## Tariff period sensor

Power 2000 tariff-period evaluation uses reported 0x1017 slots plus the device-reported 0x1015 timezone offset. Local states include:

```text
disabled
peak
off_peak
none
unknown
```

If timezone is unknown, the calculated period is unknown. Tariff ranges are
end-exclusive, and a slot whose end time is not later than its start is treated
as crossing midnight. Therefore the two all-day preset slots cover every minute
without overlapping: the second slot alone covers 23:59-00:00.

The `Tariff time slots` sensor is the read model for the reported tariff table.
It remains disabled by default. Its state is the number of reported slots, and
its attributes include `slots`, `summary`, `timezone_offset_min`, and the
read-only `preset_match` value (`all_day_peak`, `all_day_off_peak`, or `other`).
The former standalone `Tariff schedule profile` entity is not exposed.
Automations that need the current preset classification should read
`preset_match`; automations that only need the tariff applying now should read
the `Tariff period` sensor.

## Firmware registry sync

Firmware decoded from common 0x1000 is synced into Home Assistant Device Registry after the first configuration report arrives. Entity platform setup may happen before that report, so registry synchronization is intentionally delayed/update-capable.

The `Firmware` and `Communication module firmware` sensors are diagnostic and
disabled by default. DJI Home labels the latter as its dongle version. The public
baseline uses the `communication_module_firmware` entity key.

## Diagnostics and redaction

Diagnostics should use `manager_diagnostics.py` snapshots rather than directly coupling to many manager private fields.

Sensitive data policy:

- redact BLE address in exported diagnostics where appropriate;
- redact serial number;
- exclude pair key and member token;
- exclude authentication command 0x6A payloads;
- redact known identifier TLV 0x100E.

Payload capture uses a bounded in-memory ring buffer and does not continuously
write capture files. The disabled-by-default diagnostic button starts the
default capture; `dji_power_bt.start_protocol_capture` allows explicit duration and
frame limits.

The disabled-by-default `battery_status_code` diagnostic sensor retains
attributes named `raw_0x3010_hex`, `raw_0x3020_hex`, and `raw_0x3050_hex` for
charging-inhibit investigation. These are evidence fields, not decoded
availability or inhibit reasons.

## Deliberately omitted user surfaces

`Operation state` is not a device-reported state. The former entity inferred a
label from total input and output and was removed to avoid presenting an
integration guess as fact. Diagnostics retain only the objective values
`input_power_w`, `output_power_w`, and
`input_minus_output_w = input_power_w - output_power_w`.

`Refresh config` was a manual 0x60-read button. Configuration is already
synchronized during connection, by 0x62/config reports, and before writes when a
fresh snapshot is required. Do not re-add a duplicate manual refresh control
without a new user-visible need.

Do not expose an ambiguous generic charging-input entity whose name could be
mistaken for battery charging power; use the verified port-oriented AC input
entity.

Active English prose uses `off-peak`; entity keys, service fields, and enum
states use `off_peak`. Localized UI text uses the equivalent wording for each
language. Pre-public spellings are recorded only in the release history and are
not migration contracts.

## Model gating

Entity creation uses conservative model capability profiles. Runtime availability can further disable controls when the current mode does not support them.

Do not create a control just because a field can be parsed on one capture. Write safety, model support, and current runtime mode are separate questions.
