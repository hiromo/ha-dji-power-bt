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
- Limit internal `establish_connection()` attempts to 2 and use outer backoff `10/30/60/120/300` seconds.
- Track expected disconnect callbacks by weak reference and object identity.
- Do not register a second expected callback when setup-abort cleanup runs after the unexpected callback already retired the same client.

## Consequences

Reconnect can be slower than an aggressive tight retry loop, but lifecycle ownership is clearer and real-device recovery has been more reliable. Do not remove these steps as generic cleanup without equivalent field evidence and regression tests.
