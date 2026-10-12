# ADR 0002: Persistent GATT with fresh-advertisement reconnect gating

## Status

Accepted.

## Context

Early implementations could become unstable after one DJI Power device was intentionally powered off while multiple devices shared an ESPHome Bluetooth Proxy. Reusing pre-disconnect BLE device/client state and overlapping backend lifecycle transitions produced repeated reconnect failures and confusing expected-disconnect bookkeeping.

## Decision

- Keep one persistent GATT connection per enabled DJI Power entry.
- Serialize DJI Power connect/disconnect controller operations through a shared domain lock.
- After an unexpected disconnect, retain the old client temporarily as a retired client for cleanup.
- Wait 5 seconds before reconnecting.
- Discard the pre-disconnect BLEDevice and require a fresh connectable advertisement received after the disconnect.
- Wait up to 60 seconds for that fresh advertisement.
- Pass `max_attempts=2` to `establish_connection()`; the dependency may apply a separate transient-error retry budget.
- Use outer backoff `10/20/30/60` seconds, repeating 60 seconds without an attempt limit while BLE remains enabled and the manager is running. Reset progression after full readiness.
- Track expected disconnect callbacks by weak reference and object identity.
- Do not register a second expected callback when setup-abort cleanup runs after the unexpected callback already retired the same client.

## Consequences

Reconnect can be slower than an aggressive tight retry loop, but lifecycle ownership is clearer and real-device recovery has been more reliable. Do not remove these steps as generic cleanup without equivalent field evidence and regression tests.

## Backoff revision (2026-10-13)

By operator decision, replace the previous 300-second cap with 60 seconds to
reduce idle recovery latency. Retain fresh-advertisement gating, the 5-second
settle delay, retired-client cleanup, bounded disconnect calls, and shared
connection locking. Exact controller resource-release state need not be known
before a retry; failed attempts return through existing cleanup and backoff.
This is a retry-policy choice, not proof of improved real-device recovery.
