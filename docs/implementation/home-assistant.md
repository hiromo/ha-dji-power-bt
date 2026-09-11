# Home Assistant integration surface

## Config entry

`dji_power_bt` and `DjiPowerConfigFlow.VERSION = 1` begin the public compatibility
contract. Pre-public domains and versions are unsupported migration sources; see
[ADR 0007](../decisions/0007-reset-public-config-entry-baseline.md). Config-entry
fields/version and entity unique IDs are compatibility surfaces, so incompatible
changes require an explicit migration and release-contract coverage. Entity
unique IDs use the normalized BLE address plus entity key and are independent of
the config-entry version.

Stored runtime data includes the normalized BLE address, model/code, device name,
local pair key, and optional serial number. Setup-only account credentials and
member tokens are not persisted.

The pair key is excluded from GUI surfaces and diagnostics. Administrators may
inspect the matching entry's `data.local_auth_key` in
`/config/.storage/core.config_entries` for read-only recovery; never edit
`.storage`. See [authentication](../protocol/authentication.md) for the complete
secret boundary.

The user step derives model codes from Home Assistant discovery advertisements
with DJI manufacturer data (`0x08AA`); users do not type addresses or models.
Authentication accepts DJI account lookup, member-token lookup, or a known
32-character hexadecimal pair key.

Home Assistant retains a Bluetooth-discovery flow at its current server-side
step. Closing the dialog does not abort it, so reopening can show the last form;
this is flow state, not a stored device preference.

Every later setup form provides `change_auth_method`. Submitting it clears
setup-only cloud credentials and returns to the method menu without requiring
credential fields. Because the integration cannot detect dialog closure, this
explicit action is the supported reset path.

### Resetting a pre-public development installation

Back up Home Assistant and confirm a pair key, DJI account, or member token can
register the device again. While the old integration is installed, delete its
entries in the UI; remove `/config/custom_components/dji_power` and
`/config/custom_components/dji_power_bluetooth`; install `dji_power_bt`;
restart; then re-register and verify dashboard/automation entity references. If
the new code was installed first, restore the old code long enough to remove its
entries through the UI. Never force a domain/version change in `.storage` or
install old and current directories together. See
[ADR 0007](../decisions/0007-reset-public-config-entry-baseline.md).

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
