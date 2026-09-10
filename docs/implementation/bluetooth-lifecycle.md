# Bluetooth lifecycle implementation

## State progression

Normal setup is:

```text
idle
 -> connecting/resolving
 -> GATT connected
 -> subscribing to C305 notifications
 -> authenticating with 0x6A
 -> initial configuration read
 -> ready
```

`connected` means an active GATT client has been adopted. `authenticated` means 0x6A authentication succeeded. `ready` means authentication and initial configuration completed.

Do not treat a GATT connection alone as service readiness.

## Persistent client ownership

The active Bleak client is `_client`. After an unexpected disconnect callback, the same object is moved temporarily to `_retired_client` so backend cleanup can complete without confusing it with a newly connected client.

Each enabled and reachable config entry keeps one persistent GATT connection
and therefore consumes one connection slot on the local adapter or ESPHome
Bluetooth Proxy. DJI Power accepts only one BLE central at a time, so DJI Home
must release its Bluetooth connection before this integration can connect to
the same station. DJI Home access over Wi-Fi or the DJI cloud does not occupy
the station's BLE connection and can continue concurrently. Adapter and proxy
capacity planning must include one slot for every simultaneously enabled DJI
Power entry plus other connected BLE devices.

Expected-disconnect bookkeeping uses weak references. The bookkeeping table must not be an owner that keeps a dead Bleak client alive.

A callback is considered expected only when the stored weak reference resolves to the same client object by identity.

Dead weak-reference records are removed when lifecycle diagnostics are read and
on the next disconnect operation. The 300-second age limit is intentionally
applied only during a disconnect operation; reading diagnostics must not expire
a still-live expected callback record early. Diagnostics expose the remaining
count as `expected_disconnect_client_count`.

## Unexpected disconnect sequence

On an unexpected callback for the active client:

1. clear active client ownership;
2. retain the disconnected object as the retired client;
3. set `connected = False` and `authenticated = False`;
4. record `last_disconnect_reason = unexpected_disconnect`;
5. fail pending requests;
6. cancel write verification, 0x62 ACK tasks, and telemetry publication timers;
7. reset protocol reassembly/cache freshness;
8. clear the cached BLE device;
9. arm a 5-second settle delay;
10. require a **fresh connectable advertisement received after the disconnect** before reconnecting.

The fresh advertisement wait has a 60-second timeout.

This gate exists because reconnecting with a BLEDevice cached before the disconnect previously reproduced unstable backend/client ownership behavior.

## Reconnect backoff

Outer reconnect delays are:

```text
10 s, 30 s, 60 s, 120 s, 300 s
```

The internal `establish_connection()` retry count is intentionally limited to 2 so retry responsibility is not hidden inside long backend loops.

A successful ready transition resets failure state/backoff progression.

## Connection-operation lock

Connection setup/teardown operations across all DJI Power managers share a domain-wide lock. This protects finite adapter/proxy GATT capacity and avoids overlapping connect/disconnect controller transitions.

The lock is **not** a global serialization point for normal realtime traffic or every write.

Diagnostics record waiters, current holder, and per-attempt lock timings.

## Notify subscription retry

If initial `start_notify(C305)` fails or times out, setup performs a limited recovery:

1. best-effort clear GATT/service cache if supported;
2. force cleanup of the client;
3. establish one replacement client;
4. retry notification subscription.

Do not turn this into an unbounded local retry loop; the outer manager loop owns long-term retry/backoff.

## Stale backend cleanup

After repeated connection failures, the manager may call `close_stale_connections_by_address()` as best-effort recovery. It does not run on every failure.

This is backend cleanup, not evidence that a Home Assistant/ESPHome Proxy connection slot is actually leaked. Use Proxy diagnostics and client lifecycle diagnostics to distinguish the cases.

## Setup-abort bookkeeping rule

If an unexpected callback has already moved a setup client into `_retired_client`, a later setup-abort cleanup must still force backend cleanup but must **not** register another expected callback for that same client. A second callback is optional and waiting for it previously left stale expected-disconnect records.

For a still-live setup client whose intentional disconnect is initiated by setup abort, expected callback tracking remains appropriate.

## Notify watchdog

The manager tracks the monotonic time of the last notification. Current watchdog threshold is 30 seconds. A ready connection with no notifications beyond the threshold is treated as unhealthy and should flow through the connection recovery path.

## Diagnostic counters

The canonical diagnostic JSON structure, scopes, field meanings, event records,
and redaction boundaries are defined in
[`connection-diagnostics.md`](connection-diagnostics.md). This section records
the lifecycle semantics those fields must preserve.

Current connection diagnostics distinguish:

- `gatt_connect_count`: number of adopted GATT clients since manager setup;
- `gatt_reconnect_count`: GATT client adoptions after the first;
- `successful_reconnect_count`: times the manager returned to `ready` after the first `ready`;
- `last_gatt_connect_at`: last GATT adoption time;
- `last_ready_at`: last fully ready time.

Legacy `last_connect_at` and `reconnect_count` are aliases for GATT-side values.

`connection_counters.scope` is `manager_runtime_since_setup`; the counters are
not lifetime device totals. `last_unexpected_disconnect_age_s` is the elapsed
time since the last unexpected-disconnect callback.

After a successful recovery and cleanup, the expected ownership state is:

```text
active_client_is_connected = true
retired_client_present = false
expected_disconnect_client_count = 0
```

## Known diagnostic caveat

An initial connection-resolution failure can currently leave `last_disconnect_reason = connect_error` even though no previously established link disconnected. For startup failure analysis, prefer `last_connection_failure_category` and `last_connection_failure_phase`. Do not use this caveat as a reason to change lifecycle behavior without separate tests; it is a diagnostic-semantics cleanup candidate.

## Real-world validated behavior

The current reconnect design has been observed recovering a Power 1000 Mini unexpected disconnect automatically through settle -> fresh advertisement -> GATT -> authentication -> initial config -> ready, with no retained expected/retired clients afterward.

Simultaneous persistent connections to multiple DJI Power stations have also
been validated with real hardware. The shared domain lock serializes only
controller-heavy connection setup and teardown; independent per-device
telemetry continues concurrently after connection.

Treat this as evidence for preserving the sequence, not as proof that every RF/backend failure will recover within the same time.
