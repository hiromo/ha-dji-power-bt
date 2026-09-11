# Release history

This historical engineering record is not a current specification. Topical
documents under `docs/` define current behavior; for example, v0.7.5 replaced
v0.7.3's `grid_port` interpretation with AC inlet/outlet semantics.

Current public release: integration `v0.7.32`. The public compatibility baseline
remains config-entry version `1` from `v0.7.31`.

## v0.7.32

- Audited the retained Power 2000 failure and compared connection,
  authentication, configuration, and telemetry with `zuyan9/ha-dji-power-ble`.
  Authentication matches; initial `0x60` and `0x62` ACK behavior differ.
- Suppressed unchanged `0x63` writes while preserving optimistic-state
  verification and retry of expired, unconfirmed values.
- Separated queue and backend GATT deadlines; only a backend timeout recovers the
  active connection.
- Bound notifications, queued writes, and delayed ACKs to their client/generation
  and retained the true setup failure phase.
- Replaced normal address polling with an advertisement wait and removed the
  deprecated callback, while preserving cache and fresh-advertisement safeguards.
- Added bounded, payload-free traffic/contention diagnostics. Legacy `0x60`,
  conditional `0x62` ACK, PASSIVE scanning, connection parameters, and watchdog
  remain unchanged. All 119 tests passed.

See the [incident evidence](implementation/ble-disconnect-investigation-2026-09-11.md)
and [comparison/review](implementation/ble-comparison-and-review-2026-09-11.md).

## Public packaging and documentation preparation

Added HACS metadata and HACS/Hassfest validation; moved public notes to
`CHANGELOG.md` and GitHub Releases; rewrote the README as an English user guide;
documented Power 2000 Scheduled behavior, Bluetooth capacity, pair-key security,
and concurrent DJI Home Wi-Fi/cloud access; and adopted Apache License 2.0.

## Pre-public config-entry baseline reset

Before publication, reset `ConfigFlow.VERSION` from 8 to 1 without changing
current unique IDs and removed development-only migrations for versions 2-8.
Old development entries require recreation; see
[ADR 0007](decisions/0007-reset-public-config-entry-baseline.md).

## v0.7.31

- Added the missing `import contextlib` to `manager_transport.py`. The v0.7.30
  extraction of `_request()` into the transport mixin otherwise raised
  `NameError` when its `finally` cleanup called `contextlib.suppress()` after a
  normal response and aborted setup during authentication.
- Added a behavior regression test that executes the normal-response -> Future
  completion -> `finally` cleanup path.
- Audited globals after the manager/protocol split and restored missing imports
  of `capabilities_for_model_code` and `NOTIFY_WATCHDOG_TIMEOUT` in
  `manager_connection.py`.
- Added behavior tests for capability refresh from runtime manufacturer data and
  the ready-state notification watchdog.
- At that development snapshot, preserved the existing persistent GATT
  lifecycle, authentication, fresh advertisement gate, 5-second settle delay,
  `10/30/60/120/300`-second backoff, weak-reference expected-disconnect
  tracking, 0x66 fast path, XT60 telemetry, entities, services, stored settings,
  and config-entry version 8.

## v0.7.30

- Split connection diagnostics into precise GATT and readiness meanings:
  - `last_gatt_connect_at`: last adopted GATT client;
  - `last_ready_at`: last completion of authentication and initial config;
  - `gatt_connect_count`: adopted GATT clients since manager setup;
  - `gatt_reconnect_count`: GATT adoptions after the first;
  - `successful_reconnect_count`: returns to ready after the first ready.
- Kept `last_connect_at` and `reconnect_count` as compatibility aliases and added
  `connection_counters.scope = manager_runtime_since_setup`.
- Centralized reconnect, GATT, cache, and watchdog constants in
  `manager_constants.py` so runtime behavior and diagnostics use the same values.
- Introduced `manager_diagnostics.py` as the stable snapshot boundary instead of
  letting Home Assistant diagnostics read many manager-private fields directly.
- Added a structural 0x66 fast path. When the timestamp-independent body matches
  the previous body, the previous parse result and body hex are reused. Added
  `full_parse_count` and `fast_path_hit_count` diagnostics.
- Split manager responsibilities across connection, transport, payload,
  diagnostics, types, constants, and utilities while retaining the public
  manager API and state ownership in `manager.py`.
- Split the protocol implementation into frame, HMS, config, realtime,
  discovery, and common modules while retaining `protocol.py` as a compatibility
  facade for existing `from .protocol import ...` imports.

## v0.7.21

- Changed the `_expected_disconnect_client_ids` callback records from strong BleakClient
  references to `weakref.ref()` so bookkeeping cannot keep a client alive after
  its real lifecycle owners release it.
- Dead weak references are removed when diagnostics are collected and at the
  next disconnect operation.
- Preserved the existing 300-second age pruning only on disconnect operations;
  collecting diagnostics does not expire a still-live expected callback record.
- Preserved identity-based callback matching and the v0.7.11 setup-abort,
  retired-client, fresh-advertisement, settle, and backoff behavior.

## v0.7.20

- Removed unused `_config_event` and `_disconnect_event` objects and their
  unused `set()`/`clear()` calls.
- Removed unused constants from `const.py` and internal protocol helpers `mask_key()`,
  `parse_0x100d_ac_output_state()`,
  `build_0x63_ac_output_payload_from_config()`, and `now_iso()`, plus the now
  unused `datetime` import.
- Consolidated duplicated historical version assertions and source-string
  lifecycle checks into `test_release_contract.py`, preferring behavior tests
  for runtime paths.

## v0.7.11

- When an unexpected disconnect retired a client during `initial_config` or
  another setup phase, subsequent `connection_setup_abort` cleanup stopped
  registering a second expected callback for that same client.
- Backend cleanup still uses forced disconnect.
- In implementation terms, cleanup still calls `disconnect()` with
  `force=True`; only the duplicate expected-callback registration was removed.
- A normal setup abort for a still-connected client remains an expected
  disconnect.
- Added a seven-client regression reproducing field diagnostics that previously
  accumulated `expected_disconnect_client_count = 7`.

## v0.7.10

- Removed the duplicate strict requirement
  `bleak-retry-connector==4.6.1` from `manifest.json`.
- Switched fully to the connector version supplied by Home Assistant's
  `bluetooth` stack, avoiding setup failures when Home Assistant Core requires a
  newer connector. See ADR 0006.

## v0.7.9

- Renamed lifecycle diagnostic `unexpected_disconnect_age_s` to
  `last_unexpected_disconnect_age_s` without changing its calculation. It is the
  elapsed time since the last unexpected-disconnect callback.

## v0.7.8

- Synchronized main firmware from common 0x1000 into the Home Assistant Device
  Registry without a model-specific gate after the first configuration report.
- Confirmed the same firmware-field layout on Power 2000 and Power 1000 Mini.
- Observed examples at the time were:

  ```text
  Power 2000      main 01.00.1500 / communication module 03.03.0000
  Power 1000 Mini main 01.00.0300 / communication module 03.03.0000
  ```

## v0.7.7

- Retired clients that had already delivered an unexpected-disconnect callback
  were no longer registered as waiting for a second callback during cleanup or
  config-entry disable.
- This prevents a recovered connection from retaining
  `expected_disconnect_client_count = 1`.
- The expected recovered lifecycle is an active connected client, no retired
  client, and zero expected-disconnect records.

## v0.7.6

- Retained an unexpectedly disconnected client temporarily as a retired client
  for backend cleanup.
- Added the 5-second settle delay and the requirement for a new connectable
  advertisement received after the disconnect. Pre-disconnect `BLEDevice` data
  is not reused for this reconnect.
- Added bounded connection-event history spanning Power 2000 and Power 1000 Mini
  managers.
- Reduced internal `establish_connection()` attempts from four to two and made
  the outer manager backoff responsible for long-term retry.

## v0.7.5

- Replaced the ambiguous v0.7.3 `grid_port` interpretation with device-port
  semantics:
  - `group_type=1 / interface_type=1` -> `ac_inlet`;
  - `group_type=2 / interface_type=2` -> `ac_outlet`.
- Introduced the symmetric internal metrics
  `ac_inlet_input_power_w`, `ac_inlet_output_power_w`,
  `ac_outlet_input_power_w`, and `ac_outlet_output_power_w`.
- Exposed only the confirmed directions as normal entities: AC input from
  `ac_inlet_input_power_w` and AC output from
  `ac_outlet_output_power_w`. The two reverse directions remain diagnostic-only.
- Migrated the former `grid_port_input_power` entity to `ac_input_power` in
  config-entry version 8 and removed the unconfirmed `grid_port_output_power`.
- Avoided a site-topology assumption: the source connected to the AC inlet could
  be utility power, a generator, another inverter, or another power station.

### Power 2000 AC/SDC evidence

With simultaneous AC and SDC solar input, DJI Home displayed total input
1,515 W, AC 1,478 W, and SDC 37 W. The corresponding 0x3030 report contained
the same total, `group_type=1 / interface_type=1 / input_w = 1,478 W`, and
`group_type=4 / interface_type=5 / input_w = 37 W`. This confirmed the Power
2000 AC-inlet input mapping.

## v0.7.4

- Removed `sensor.<device>_operation_state`. It was a local inference from total
  input/output, not a device-reported state. Retained objective diagnostic values
  `input_power_w`, `output_power_w`, and
  `input_minus_output_w = input_power_w - output_power_w`.
- Removed `button.<device>_refresh_config`. Configuration is synchronized during
  connection, by configuration reports, and before writes when necessary, so a
  manual 0x60 button duplicated automatic behavior.
- Config-entry version 7 removes both obsolete registry entries.

## v0.7.3

This section records a superseded interpretation for migration history only.

- Temporarily interpreted `group_type=1 / interface_type=1` as a bidirectional
  `grid_port` and exposed `grid_port_input_power` and
  `grid_port_output_power`. v0.7.5 replaced this with the current AC
  inlet/outlet model.
- The exact historical entities were
  `sensor.<device>_grid_port_input_power` and
  `sensor.<device>_grid_port_output_power`; the existing
  `sensor.<device>_ac_output_power` remained the Power 2000 AC-outlet total.
- At that point `group_type=2 / interface_type=2 / input_w` was retained only as
  diagnostic `ac_input_power_w`; the v0.7.5 symmetric port model superseded that
  name.
- Removed the misleading `charging_input_power` entity.
- Standardized English prose on `off-peak`, identifiers and states on
  `off_peak`, and the Japanese UI on its localized off-peak wording.
- Renamed active identifiers:
  - `offpeak_charging` -> `off_peak_charging`;
  - `offpeak_charging_power` -> `off_peak_charging_power`;
  - `all_day_offpeak` -> `all_day_off_peak`.
- Config-entry version 6 removes obsolete registry entries rather than retaining
  ambiguous aliases. Existing automations had to update service-field and state
  identifiers to the new spelling.

## v0.7.2

- Added `dji_power.set_scheduled_energy_settings` so energy optimization, peak
  discharging, off-peak charging, and off-peak charging power can be updated in
  one 0x1018 transaction.
- All fields are optional, but at least one is required. Unspecified confirmed
  fields and all unknown bytes retain the current device-reported value.
- If every requested value already matches, the BLE write is skipped.
- If the only real change is off-peak charging power, the high-frequency passive
  verification policy is retained and no forced 0x60 readback is added.
- Automation sequences that previously issued `number.set_value` plus two switch
  calls can use this one service transaction instead.
- The 86-byte (`0x56`) 0x1018 value is handled by read-modify-write. Confirmed
  edit/preserve ranges are maintained in `protocol/commands.md`.
- Tariff time slots are separate 0x1016/0x1017 records and are not modified by
  this service.

## v0.7.1

- Changed all-day peak and all-day off-peak preset icons to moon and sun
  respectively.
- Made `Tariff schedule profile` disabled by default while retaining the English
  enum displays `All-day peak`, `All-day off-peak`, and `Other` in every locale.
- Preserved the last disconnect reason/time after reconnect and added the last
  connection-attempt failure/time to diagnostics.

## v0.6.3

- Reused a general configuration snapshot reported by 0x62/0x60 for up to 30
  seconds for read-modify-write.
- High-frequency Power 2000 off-peak charging-power writes complete on the
  matching 0x63 ACK/result code zero and do not force an active readback.
- Low-frequency writes wait 12 seconds for passive 0x62 verification and perform
  one 0x60 readback only if needed.
- Complete AC/SDC and charging-mode table writes use only device-reported tables
  no older than 15 seconds; older or incomplete tables require a fresh read or
  reject the operation.
- Added config-read, cache-hit, and verification-readback diagnostics.
- Preserved user-customized entity IDs during unique-ID migrations; only an
  integration-generated old suffix is renamed.

### Frame reassembly

- Stopped assuming a one-to-one boundary between GATT notifications and DJI
  frames.
- Added split-frame reassembly, multiple-frame extraction, length/CRC8/CRC16
  validation, conservative resynchronization, disconnect/re-auth buffer reset,
  and `gatt_frame_reassembly` diagnostics.

### ACK and state verification

- Separated matching-sequence 0x63 ACK/result-code success from later device
  state verification.
- Applied optimistic Home Assistant state after ACK success.
- Used passive 0x62 or delayed low-frequency 0x60 readback for verification.
- Revisions prevent an older verification from overriding a newer same-property
  write; the old attempt ends as `superseded_by_new_write`.
- Added `write_history`, ACK sequence, verification source/pending state, and
  `ble_traffic_control` diagnostics.

### Model/table behavior consolidated in this period

- Power 1000 Mini 0x100D was treated as a complete output-interface table, not
  an AC-only record. Observed entries were AC, USB-C1, USB-C2, USB-A1, USB-A2,
  and SDC1. Power 2000 current captures contained only an AC entry.
- Writers preserve every parsed 0x100D record and its order, change only the
  target state, and reject unknown/incomplete tables.
- Power 1000 Mini 0x101E exposed `slow` (nominal 500 W) and `fast` (nominal
  1,000 W) modes. They are discrete modes, not a continuous power number.
- Power 2000 off-peak charging power uses a verified model-profile step of
  10 W. The value observed at 0x1018 offset 34 remains only a candidate and is
  not adopted automatically for unknown models.
- Power 2000 energy optimization exposes `disabled` and `scheduled`. Scheduled
  controls become unavailable while disabled. `Tariff period` remains available
  and reports `disabled`. Unknown modes remain raw/unsupported; basic telemetry
  continues while 0x1018 Scheduled writes are blocked.
- Main and communication-module firmware use the common 0x1000 layout. The old
  `secondary_firmware` unique ID migrated to
  `communication_module_firmware`, preserving a user-customized entity ID.
- Raw `battery_status_code`, 0x3010, 0x3020, and 0x3050 data were retained for
  high-temperature charging-inhibit investigation without inventing a
  `charging_allowed` or `inhibit_reason` meaning.
