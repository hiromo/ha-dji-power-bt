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

The retry delays are 10, 20, 30, then 60 seconds. Retries continue at the
60-second cap without an attempt limit while BLE is enabled and the runner is
active. Full readiness resets the progression.

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

Initial setup does not require a 0x62 report. All five initial GETs use the normal
request/write deadlines; authentication or GET failure aborts setup. Report ACKs
remain best-effort during both initialization and normal operation. Backend write
timeouts still mark the active transport unhealthy through the existing path.

Ordinary setting calls before readiness raise `HomeAssistantError` without
sending prewrite reads or writes. They are not deferred for later execution.

`_request()` creates a future before writing and waits for a matching response. The pending entry is removed in `finally`; incomplete futures are cancelled and completed-future exceptions are consumed safely so cleanup does not create unhandled-future warnings.

## Write errors

A nonzero expected-property result in a 0x63 ACK is a write failure and is surfaced to Home Assistant. Do not pretend success and wait for a later report.

A successful ACK sets verification pending. Verification can succeed from a later 0x62/config report or, for low-frequency policies, an explicit delayed 0x60 readback.

High-frequency off-peak power writes intentionally do not trigger active readback for every write.

## Diagnostics that matter during field debugging

See [`connection-diagnostics.md`](connection-diagnostics.md) for the canonical
connection-diagnostic JSON structure, field scopes and lifetimes, failure
categories, lifecycle state, event-history schema, and redaction contract.

For transport and protocol failures, inspect pending requests, write timeouts, frame reassembly, and write verification history.

## Payload security

Never capture or export:

- pair key;
- member token;
- password/CAPTCHA secrets;
- 0x6A authentication payloads.

Redact known identifiers such as serial/MAC and 0x100E in exported diagnostics.
