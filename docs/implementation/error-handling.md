# Error handling and diagnostics

## Principles

1. Keep the manager loop alive across recoverable BLE failures.
2. Record enough phase/category information to distinguish RF/device issues from code/lifecycle issues.
3. Abort the current connection setup cleanly after authentication/configuration failure.
4. Never let diagnostic bookkeeping own a dead BLE client.
5. Treat write ACK completion separately from state verification.
6. Preserve secrets and identifiers in diagnostics.

## Connection failure phases

Connection events record the current phase, such as:

```text
idle
connecting
resolving
subscribing
authenticating
initial_config
ready
disconnect_settle
waiting_fresh_advertisement
backoff
disconnecting
```

Use `last_connection_failure_phase` plus `last_connection_failure_category` for the most useful failure diagnosis.

A connection error should not be interpreted as a GATT-slot leak without Bluetooth Proxy/adapter evidence.

## Outer retry behavior

Recoverable connection exceptions increment `consecutive_connect_failures`, save `last_connection_error`, categorize the failure, and schedule the configured backoff. The manager runner continues.

The retry schedule is capped at 300 seconds.

## Setup abort

Failure after a client has been created must:

- fail pending request futures;
- force backend client cleanup;
- avoid double-registering an expected callback for an already retired client;
- clear active/retired ownership as appropriate;
- set connected/authenticated false;
- cancel verification/ACK/telemetry tasks;
- reset protocol reassembly and cache freshness.

## GATT write timeout

Lock acquisition and backend write completion each have a 10-second timeout.
Both increment the legacy aggregate `gatt_write_timeout_count`, update
`last_gatt_write_timeout_at`, and fail the caller with
`DjiPowerConnectionError`. Additive `gatt_traffic` counters distinguish the
two stages. A queue timeout alone does not change transport health; a timed-out
backend write records the connection error and marks its still-active
generation unhealthy. An old backend timeout cannot poison a replacement link.

Do not allow a stuck ACK task or old write to hold the write lock indefinitely across reconnect.

Capture the setup phase before an unexpected-disconnect callback resets it to
`idle`. Setup-abort handling preserves that captured phase in the failed event.

## Request timeout

`_request()` creates a future before writing and waits for a matching response. The pending entry is removed in `finally`; incomplete futures are cancelled and completed-future exceptions are consumed safely so cleanup does not create unhandled-future warnings.

## Write errors

A nonzero expected-property result in a 0x63 ACK is a write failure and is surfaced to Home Assistant. Do not pretend success and wait for a later report.

A successful ACK sets verification pending. Verification can succeed from a later 0x62/config report or, for low-frequency policies, an explicit delayed 0x60 readback.

High-frequency off-peak power writes intentionally do not trigger active readback for every write.

## Diagnostics that matter during field debugging

See [`connection-diagnostics.md`](connection-diagnostics.md) for the canonical
connection-diagnostic JSON structure, field scopes and lifetimes, failure
categories, lifecycle state, event-history schema, and redaction contract.

Connection:

- current phase;
- GATT connect/reconnect/successful-reconnect counters;
- last failure phase/category/error;
- active/retired/expected client state;
- fresh-advertisement gate state;
- domain connection-lock holder/waiters;
- stale backend cleanup count.

Transport:

- pending request count;
- write-lock context/age;
- GATT write timeout count;
- reassembly CRC/length/discard counters;
- config read/cache-hit counters;
- verification readback/timeout counters.

Protocol:

- safe latest payloads;
- 0x66 full-parse/fast-path counts and bounded pattern history;
- raw unresolved battery/config fields where intentionally retained.

Stable grouped diagnostic surfaces include:

- `connection_counters`, with
  `scope = manager_runtime_since_setup`, GATT adoption/re-adoption counts, and
  fully successful reconnect count;
- compatibility aliases `last_connect_at` and `reconnect_count` for existing
  diagnostic consumers;
- `client_lifecycle.expected_disconnect_client_count` and
  `client_lifecycle.last_unexpected_disconnect_age_s`;
- `gatt_frame_reassembly` for valid frames, CRC/length failures, discarded
  bytes, and incomplete buffering;
- `ble_traffic_control` for `config_read_request_count`,
  `config_cache_hit_count`, `verification_readback_count`, and
  `passive_verification_timeout_count`;
- `off_peak_charging_power_step` for the configured model-profile step and the
  diagnostic-only 0x1018 offset-34 candidate;
- `write_history`, including ACK sequence, verification source/state, and
  `superseded_by_new_write` outcomes.

## Known diagnostic semantic caveat

`last_disconnect_reason` can currently contain `connect_error` after an initial connection attempt failed before a link was established. For startup analysis, use the explicit connection-failure phase/category fields. A future cleanup may split "last disconnect" from "last connection attempt failure" more strictly; do not combine that semantic cleanup with BLE lifecycle changes unnecessarily.

## Payload security

Never capture or export:

- pair key;
- member token;
- password/CAPTCHA secrets;
- 0x6A authentication payloads.

Redact known identifiers such as serial/MAC and 0x100E in exported diagnostics.
