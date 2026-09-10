# Connection diagnostics contract

This document defines the current Home Assistant diagnostic surface for DJI
Power Bluetooth connection setup, ownership, failure, and recovery. The
lifecycle design itself is documented in
[`bluetooth-lifecycle.md`](bluetooth-lifecycle.md); this document defines how to
interpret the exported evidence.

`manager_diagnostics.py` is the stable snapshot boundary. Home Assistant's
`diagnostics.py` applies redaction to that snapshot before export. Code outside
the manager implementation should consume the snapshot instead of reading
manager-private connection fields directly.

## Export structure and scope

Downloaded config-entry diagnostics have this relevant structure:

```text
entry
state
  connection fields for the selected config entry
  connection_counters
  client_lifecycle
  connection_event_history_limit
  connection_event_history
  domain_connection_runtime
    connection_lock_holder
    connection_lock_waiters
    manager_count
    managers
    connection_event_history_limit
    connection_event_history
```

The scopes are deliberately different:

- `state` is a snapshot of the manager for the selected config entry;
- `state.client_lifecycle` is current ownership and reconnect-gate state, not a
  history;
- `state.connection_event_history` contains only that manager's most recent 50
  connection events;
- `state.domain_connection_runtime` summarizes every currently loaded DJI Power
  manager and contains the most recent 100 cross-device connection events;
- `connection_counters.scope = manager_runtime_since_setup` means the counters
  begin when the current manager object is created. Reloading its config entry
  replaces the manager and resets its counters and local history;
- the domain runtime survives an individual config-entry reload within the same
  Home Assistant process, but its shared history and IDs reset on Home Assistant
  restart.

Diagnostics are snapshots only. They are not written as a continuous log.
Bounded histories discard the oldest records when their limits are reached.

## Time and correlation values

Fields ending in `_at` and event `recorded_at` are UTC ISO-8601 wall-clock
timestamps. They may be compared with Home Assistant logs.

Durations and ages ending in `_s` are seconds. Event `monotonic_time` is an
event-loop monotonic clock value: it is useful for ordering and measuring events
from the same Home Assistant runtime, but it is not a wall-clock timestamp and
must not be compared across restarts.

`attempt_id` is allocated domain-wide for one complete connection attempt.
`event_id` is allocated domain-wide for one event. Use these values to correlate
a selected entry's local history with `domain_connection_runtime` when multiple
devices share an adapter or Bluetooth Proxy.

`connection_generation` increments whenever the manager adopts a GATT client.
`client_id` and the client IDs in `client_lifecycle` are process-local object
identifiers for short-term event correlation only. They are not device IDs and
are not stable across client replacement or Home Assistant restart.

## Readiness and connection phase

The three primary readiness fields have distinct meanings:

- `connected`: the manager has adopted a GATT client;
- `authenticated`: command `0x6A` authentication succeeded for that client;
- `connection_phase = ready`: authentication and the initial configuration read
  both completed.

An adopted or backend-connected client alone is not proof that entities and
writes are ready. Use `authenticated` and `connection_phase` together when
diagnosing setup.

Current `connection_phase` values are:

| Value | Meaning |
| --- | --- |
| `idle` | No setup or teardown operation is currently active. |
| `connecting` | A connection attempt is starting or Bleak is establishing GATT. |
| `resolving` | Home Assistant Bluetooth is resolving the configured address. |
| `subscribing` | C305 notification subscription is being established. |
| `authenticating` | Local pair-key authentication is in progress. |
| `initial_config` | The initial `0x60` configuration read is in progress. |
| `ready` | Authentication and initial configuration completed. |
| `disconnect_settle` | The post-unexpected-disconnect settle delay is active. |
| `waiting_fresh_advertisement` | A new connectable advertisement is required. |
| `backoff` | The outer retry delay is active. |
| `disconnecting` | Intentional or cleanup teardown is in progress. |

New phases may be added, so diagnostic consumers must tolerate unknown values.
Renaming or changing the meaning of an existing phase requires documentation
and behavior-test updates.

## Connection counters and retained outcomes

`connection_counters` is the canonical grouped counter surface:

| Field | Meaning |
| --- | --- |
| `scope` | Always `manager_runtime_since_setup`. |
| `gatt_connect_count` | Number of GATT clients adopted by this manager, including the first. |
| `gatt_reconnect_count` | GATT client adoptions after the first; this can increase even if later authentication or initial configuration fails. |
| `successful_reconnect_count` | Returns to fully `ready` after the first successful `ready`. |

The same counters also remain at the top level. `last_gatt_connect_at` records
the last client adoption and `last_ready_at` records the last fully ready
transition. Legacy `last_connect_at` and `reconnect_count` are aliases for
`last_gatt_connect_at` and `gatt_reconnect_count`; they must not be interpreted
as full-readiness values.

`last_disconnect_reason` and `last_disconnect_at` deliberately survive a
successful reconnect so a later diagnostic can still explain why recovery was
needed. `last_connection_error`, `last_connection_error_at`,
`last_connection_failure_category`, and `last_connection_failure_phase` also
describe the most recently recorded failure; they are not a claim that the
current connection is still failed. Read them together with the current
readiness fields.

`consecutive_connect_failures` resets after a complete successful setup.
`last_retry_delay_s` is the most recently selected outer delay and becomes
`null` after successful setup. `stale_connection_cleanup_count` counts
successful best-effort backend cleanup calls, not proven Bluetooth Proxy slot
leaks.

An initial resolution/setup failure can currently set
`last_disconnect_reason = connect_error` even though no established link was
disconnected. For initial setup failures, prefer
`last_connection_failure_category` and `last_connection_failure_phase`.

## Failure categories

`last_connection_failure_category` and failed-attempt event
`failure_category` use these diagnostic categories:

| Value | Meaning |
| --- | --- |
| `out_of_slots` | The backend reported no available connection slot. |
| `device_not_found` | The configured address was not found, reachable, or available. |
| `connection_aborted` | The connection was aborted or cancelled. |
| `timeout` | A timeout occurred directly or in a wrapped cause/context. |
| `authentication` | Authentication failed. |
| `start_notify` | Notification subscription failed. |
| `other` | No more specific category matched. |

The classifier is diagnostic and intentionally conservative. A category is not
proof of the physical root cause. In particular, `out_of_slots` is backend
evidence that should be compared with Home Assistant adapter/Proxy diagnostics;
it does not by itself prove a permanently leaked slot.

`last_connection_failure_phase` records the phase in which the failed attempt
was operating. It is more precise than guessing from the exception text.

## Current client lifecycle

`client_lifecycle` contains current ownership and reconnect-gate state:

| Field | Meaning |
| --- | --- |
| `active_client_present` | The manager currently owns an active client object. |
| `active_client_id` | Process-local correlation ID for that object, otherwise `null`. |
| `active_client_is_connected` | Best-effort backend `is_connected`; `null` when no client or unavailable. |
| `retired_client_present` | An old client is retained temporarily for cleanup. |
| `retired_client_id` | Process-local correlation ID for the retired object. |
| `retired_client_is_connected` | Best-effort backend state for the retired object. |
| `expected_disconnect_client_count` | Live clients whose intentional disconnect callback is still expected. |
| `fresh_advertisement_required` | Reconnect is gated until a post-disconnect advertisement arrives. |
| `fresh_advertisement_received_at` | Wall-clock time of the last accepted fresh advertisement. |
| `last_unexpected_disconnect_age_s` | Monotonic age since the latest unexpected callback in this manager runtime. |
| `reconnect_settle_remaining_s` | Remaining settle delay while the fresh-advertisement gate is active. |
| `active_connection_attempt_id` | Domain-wide ID of the attempt currently in progress. |

Expected-disconnect records use weak references. Reading diagnostics removes
dead weak references but does not apply the 300-second age expiry to a live
client; age-based expiry remains part of disconnect processing. The normal
post-recovery ownership state is:

```text
active_client_is_connected = true
retired_client_present = false
expected_disconnect_client_count = 0
fresh_advertisement_required = false
```

If `retired_client_present` or `expected_disconnect_client_count` remains
nonzero, use event `client_id`, `expected_disconnect`,
`callback_for_active_client`, and `callback_for_retired_client` to distinguish
an expected callback that has not arrived from an unexpected or stale callback.

## Connection event histories

Every connection event has these common fields:

| Field | Meaning |
| --- | --- |
| `event_id` | Domain-wide event sequence number. |
| `recorded_at` | UTC wall-clock timestamp. |
| `monotonic_time` | Monotonic timestamp for same-runtime ordering/durations. |
| `entry_id` | Config entry that recorded the event. |
| `model` and `address` | Device context; the exported address is masked. |
| `event` | Event name. |
| `phase` | Manager phase when the event was recorded. |
| `attempt_id` | Associated connection attempt, if any. |
| `connection_generation` | Adopted-client generation at that point. |
| `client_id` and `client_is_connected` | Optional backend-client correlation and state. |
| `expected_disconnect` | `true`, `false`, or `null` when not applicable. |
| `scanner_source` | Best available Home Assistant Bluetooth source. |
| `device_resolution` | Most recent resolution route. |
| `fresh_advertisement_required` | Gate state when the event was recorded. |

Events may add context-specific fields such as `attempt_duration_s`,
`failure_category`, `failure_phase`, `lock_context`, `lock_wait_s`,
`disconnect_context`, `retry_delay_s`, `exception_class`, and
`exception_message`. Consumers must tolerate absent and newly added optional
fields.

Important event families are:

- `connect_attempt_start`, `connect_attempt_failed`,
  `connect_attempt_cancelled`, and `connect_attempt_ready` for whole-attempt
  boundaries;
- `connection_lock_wait_start`, `connection_lock_acquired`, and
  `connection_lock_released` for cross-device controller serialization;
- `client_adopted`, `notify_start_requested`, `notify_started`,
  `notify_start_failed`, `authentication_start`, `authenticated`, and
  `initial_config_complete` for setup progress;
- `disconnect_sequence_start`, `disconnect_requested`, `disconnect_callback`,
  `disconnect_complete`, `disconnect_failed`, and
  `disconnect_sequence_complete` for teardown ownership;
- `unexpected_disconnect_reconnect_gate_armed`,
  `unexpected_disconnect_settle_start`, `fresh_advertisement_wait_start`,
  `fresh_advertisement_wait_timeout`, and `fresh_advertisement_received` for
  reconnect gating;
- `retry_scheduled`, `connection_health_failed`,
  `cached_ble_device_used`, and `stale_disconnect_callback_ignored` for
  recovery and exceptional paths.

The event-name set is extensible. Adding an event is compatible; renaming or
removing an established event used for field diagnosis requires corresponding
documentation and behavior-test changes.

## Domain-wide runtime

`domain_connection_runtime` exists to diagnose interactions between multiple
DJI Power entries sharing Home Assistant Bluetooth resources.

- `connection_lock_holder` is `entry_id:context` for the manager currently
  holding the domain connection-operation lock, otherwise `null`;
- `connection_lock_waiters` is the number of managers currently waiting for
  that lock;
- `manager_count` and `managers` summarize all currently loaded managers;
- each manager summary includes readiness, phase, active/retired ownership, and
  fresh-advertisement-gate state;
- its event history uses the same domain-wide `event_id` and `attempt_id` values
  as each local history, allowing cross-device ordering.

The lock serializes connect/disconnect controller operations only. A nonzero
waiter count does not mean normal telemetry or all GATT writes are globally
blocked.

## Resolution and identity evidence

Connection diagnostics also retain how Home Assistant found and identified the
target:

- `last_device_resolution`: `ha_current`, `ha_cached`,
  `fresh_after_disconnect`, or `unavailable`;
- `configured_address`: authoritative address owned by the config entry;
- `resolved_ble_address` and `resolved_ble_name`: selected Home Assistant
  `BLEDevice` evidence;
- `advertisement_source`, `advertised_name`, `manufacturer_ids`, model fields,
  and `advertised_bound`: latest advertisement evidence;
- `bluetooth_source`: connector source associated with the adopted client;
- `identity_status`: address/manufacturer/protocol validation outcome.

Names and advertised model fields are diagnostic evidence, not connection
identity. The configured normalized BLE address is authoritative, and successful
`0x6A` authentication is the protocol-level check.

## Redaction and compatibility rules

Before Home Assistant exports the snapshot, the integration:

- masks the device-specific portion of BLE addresses;
- masks MAC addresses embedded in exception messages;
- redacts the serial number and local pair key in config-entry data;
- excludes authentication command `0x6A` payloads and member tokens;
- redacts known identifier TLV `0x100E` and raw base-identity bytes.

Do not add pair keys, member tokens, account credentials, authentication
payloads, or unredacted persistent identifiers to connection events or failure
messages.

Treat the documented grouping, field names, and semantics as a diagnostic
compatibility surface. Additive fields and events are allowed. Renaming,
removing, changing scope, or changing meaning requires updating this document,
`manager_diagnostics.py`, redaction where applicable, and behavior/release
contract tests in the same change.
