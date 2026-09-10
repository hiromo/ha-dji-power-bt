# Architecture

## Scope

This integration monitors and controls DJI Power devices through local BLE and exposes the result through Home Assistant. Normal runtime operation is local-only. DJI account access, when used, exists only to obtain a local pair key during configuration.

Public compatibility baseline: integration `v0.7.31`, domain
`dji_power_bt`, Home Assistant config-entry version `1`.

Private development began in early June 2026. Power 2000 and Power 1000 Mini
have received sustained real-environment validation since then, including
simultaneous multi-station connections. This history strengthens confidence in
the verified paths without promoting unverified models or firmware behavior to
confirmed support.

## Design goals

1. Keep BLE runtime local and persistent.
2. Treat the DJI protocol as reverse engineered and preserve uncertainty explicitly.
3. Prefer conservative behavior over destructive writes when a payload is not fully understood.
4. Keep model-specific behavior isolated and documented.
5. Make disconnect/reconnect behavior diagnosable without retaining stale BLE clients.
6. Minimize BLE traffic while still validating writes.
7. Keep Home Assistant entity semantics stable across internal refactors.
8. Keep repository Markdown, not chat memory, as the long-term engineering record.

## High-level data flow

```text
Home Assistant ConfigEntry
        |
        v
DjiPowerManager
        |
        +-- connection lifecycle ------> HA Bluetooth / bleak-esphome / GATT
        |
        +-- protocol transport --------> C304 write characteristic
        |                                C305 notify characteristic
        |
        +-- DUM-like frame reassembly -> command routing
        |                                  |-- 0x60 config read
        |                                  |-- 0x61 realtime telemetry
        |                                  |-- 0x62 config push/report
        |                                  |-- 0x63 setting write + ACK
        |                                  |-- 0x66 HMS/auxiliary report
        |                                  `-- 0x6A authentication
        |
        +-- state/cache/verification
        |
        `-- HA entities/services/diagnostics
```

## Runtime ownership

One config entry owns one `DjiPowerManager` and one persistent BLE connection when BLE is enabled and the device is reachable.

Each persistent connection consumes one adapter/proxy GATT slot. Multiple DJI
Power connections have been validated with real hardware, subject to the
connection capacity of the selected local adapter or ESPHome Bluetooth Proxy.

`entry.runtime_data` stores the manager. Entity platforms read manager state and subscribe to manager update callbacks.

A domain runtime shared by all DJI Power entries owns the connection-operation lock and the domain-wide connection event history. Connection setup/teardown is serialized across DJI Power devices; normal per-device notification traffic is not globally serialized.

## Manager modules

`manager.py`
: Public manager API, state ownership, Home Assistant-facing control methods, payload-capture entry point, and device info.

`manager_connection.py`
: Discovery/resolution, connection setup, notification subscription, disconnect lifecycle, reconnect gating, retry/backoff, stale backend cleanup, client ownership, and connection event diagnostics.

`manager_transport.py`
: DUM-like request/response transport, GATT writes, authentication, configuration reads, unsolicited command handling, write ACK processing, cache use, write verification, and 0x62 ACKs.

`manager_payload.py`
: Safe payload capture, write history, reassembly diagnostics, and 0x66 HMS fast-path bookkeeping.

`manager_diagnostics.py`
: Stable diagnostic snapshots. `diagnostics.py` should consume this layer instead of reaching deeply into manager private fields.

`manager_types.py`
: Runtime state and exception/data types.

`manager_constants.py`
: Shared runtime timeouts, cache ages, history limits, and reconnect policy constants.

`manager_utils.py`
: Small shared helpers.

## Protocol modules

`protocol.py`
: Compatibility facade. Existing imports from `.protocol` are intentionally preserved.

`protocol_frame.py`
: DUM-like frame structure, CRC8/CRC16, stream reassembly, and generic TLV scanning.

`protocol_discovery.py`
: DJI manufacturer-data parsing for discovery and model code selection.

`protocol_config.py`
: 0x60/0x62 configuration parsing, 0x63 write payload construction, tariff records, output-interface tables, charging modes, and write-result decoding.

`protocol_realtime.py`
: 0x61 realtime telemetry, battery fields, total power, group/interface/port power records.

`protocol_hms.py`
: Provisional 0x66 HMS parsing and timestamp-independent fast-path support.

`protocol_common.py`
: Endian helpers, address normalization, pair-key validation, and interface/group names.

## Home Assistant modules

`config_flow.py`
: Bluetooth discovery, device selection, local pair-key setup, optional one-time DJI account/member-token lookup, options, and reauthentication. `ConfigFlow.VERSION = 1`.

`__init__.py`
: Integration/service setup, manager lifecycle, platform forwarding, and unload.

`sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`, `binary_sensor.py`
: Home Assistant entity surfaces. Availability is intentionally stricter than raw state existence for many entities.

`cloud.py`
: Experimental private DJI Home API client used only during setup to retrieve a local pair key. Normal runtime must not depend on it.

`capabilities.py`
: Conservative static model capability hints. Device-reported tables can supplement these hints only when their semantics are understood safely.

`write_policy.py`
: Write verification policy. High-frequency controls and low-frequency controls intentionally use different readback behavior.

`tariff.py`
: Local evaluation of Power 2000 tariff periods from reported schedule slots and device timezone.

## Concurrency model

- `_connect_lock` serializes connection setup/teardown per manager.
- The domain connection-operation lock serializes controller-heavy connect/disconnect operations across DJI Power entries.
- `_write_lock` serializes GATT writes per device and is covered by an outer write timeout.
- Request/response matching uses `(connection_generation, sequence)` so a response from an old BLE generation cannot satisfy a request on a newer link.
- Configuration-setting public methods use an operation lock so read-modify-write sequences do not race each other.

## State publication

BLE notifications are parsed at their native rate, approximately once per
second on currently tested stations. Home Assistant listener notifications for
realtime telemetry are throttled to the configured interval, default 5 seconds
and constrained to 1-60 seconds.

Configuration reports and write state changes can publish independently of telemetry throttling.

## Compatibility boundaries

From the public version 1 baseline onward, treat the following as compatibility surfaces:

- integration domain `dji_power_bt` and package path
  `custom_components.dji_power_bt`
- config-entry schema and `ConfigFlow.VERSION`
- entity unique IDs and semantic meaning
- service names and fields
- `.protocol` facade exports
- diagnostic keys intentionally used for field troubleshooting

Internal file layout may change, but compatibility changes require explicit migration/documentation/tests.

## Testing layers

- protocol parser/builder tests for captured bytes
- manager behavior tests for connection, cleanup, reconnect, request/response, and write verification
- release-contract tests for compatibility invariants
- release-specific regression tests for known failures

Prefer executable behavior tests to tests that merely search source text.
