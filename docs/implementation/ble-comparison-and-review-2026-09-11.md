# BLE implementation comparison and proposed-change review: 2026-09-11

This follows the [diagnostic investigation](ble-disconnect-investigation-2026-09-11.md).
Baseline: local `46bce57`, integration `0.7.31`. Comparison source:
`zuyan9/ha-dji-power-ble` at
`4682acbef33bfb9b4734818cc640f59dbd7c2758`. That public repository was inspected
in a temporary checkout. No hardware or HA instance was operated.

The operator additionally reports that earlier HA-side interventions never
resolved comparable faults, whereas the present recovery followed successful
DJI Home Bluetooth use. HA BLE was disabled first; DJI Home displayed all
information normally for about one minute. This strengthens the priority of
investigating a station-side state change caused by the official app. It does
not identify the responsible packet or exclude Android's different link
negotiation/teardown. The tentative app time is not reliable enough to align it
with one exact diagnostic event.

The pasted AI review is a list of claims to check, not evidence of actual
traffic counts or proof of the failure's origin. In particular, references to
past mainboard/inverter errors in that text were not independently verified by
this investigation.

## Communication comparison for Power 2000 and Power 1000 Mini

| Stage | This integration | zuyan9 comparison |
| --- | --- | --- |
| GATT | C304 writes, C305 notifications; full DUML frames; `response=True` | Same |
| DUML | Source `02`, destination `AB`, command set `5A`, version 1, DJI CRC8/CRC16 | Same |
| Authentication | Two `0x6A` exchanges: challenge, then pair-key proof | Same for the two target models |
| Initial configuration | One `0x60`, retained 48-byte literal / 61-byte DUML frame | Two `0x60` calls: `00 01 10`, then `00 04 10`; each a 16-byte DUML frame |
| Timing | Notify, 200 ms pause, authenticate, GET, ready | Notify, authenticate, two GETs, wait up to five seconds for first parsed `0x61`; missing initial report is nonfatal |
| Steady telemetry | Persistent station pushes `0x61` and `0x66`; no periodic metrics GET | Same push model |
| Configuration push | ACK `0x62` only for `AB -> 02`, type `40`; same sequence, response type `80`, payload `01` | Parses `0x62`, sends no application ACK |
| Reconnect | Retired-client cleanup, five-second settle, post-disconnect fresh advertisement, shared lifecycle lock, outer backoff | Coordinator schedules entry reload; setup checks recent advertisement, otherwise awaits advertisement |
| Sequence | First request 10001; continues across reconnects in one manager | First request 4097; a new device object on entry reload restarts the sequence |
| Disconnect | Notification unsubscribe and GATT disconnect | Same basic operations; no DJI session-close/reset packet |

Sources: [device implementation](https://github.com/zuyan9/ha-dji-power-ble/blob/4682acbef33bfb9b4734818cc640f59dbd7c2758/custom_components/dji_power_ble/device.py),
[DUML codec](https://github.com/zuyan9/ha-dji-power-ble/blob/4682acbef33bfb9b4734818cc640f59dbd7c2758/custom_components/dji_power_ble/duml.py),
[coordinator](https://github.com/zuyan9/ha-dji-power-ble/blob/4682acbef33bfb9b4734818cc640f59dbd7c2758/custom_components/dji_power_ble/coordinator.py),
[entry setup](https://github.com/zuyan9/ha-dji-power-ble/blob/4682acbef33bfb9b4734818cc640f59dbd7c2758/custom_components/dji_power_ble/__init__.py).

**Confirmed by synthetic execution:** both real authentication/request builders
produce identical authentication frames after normalizing sequence numbers,
using synthetic credentials. No authentication payload was exported. A fake
GATT backend fragmented replies into seven-byte notifications. Initial GET
payload/frame lengths were respectively `48/61` versus `3/16, 3/16`. Feeding
the same valid `0x62/0x40` notification generated one ACK here and zero there.
This proves the code-level difference, not real-device compatibility or repair.

The GET difference is the first initialization comparison worth pursuing:
retained failures repeatedly authenticate and then disconnect during initial
configuration. Request *content/grammar* matters, not just length. Authentication
already sends a 51-byte frame successfully in both implementations, so a simple
"every write over 20 bytes fails" theory does not fit these logs. Actual MTU,
backend long-write behavior, and station processing still require measurement.
The legacy GET's field boundaries also need validation; see
[unknowns](../protocol/unknowns.md#configuration-get-grammar-and-recovery).

There is no extra magic reset, session-finalization, periodic keepalive, or
report-subscription command in the inspected comparison runtime. Neither does
it prove that the official app has no such exchange. The comparison's original
Power 1000 encrypted transport path is model-specific and is not used for
Power 2000/Mini.

External field evidence is limited but relevant: [Mini issue #4](https://github.com/zuyan9/ha-dji-power-ble/issues/4)
reports about ten reconnects over two days, successful report/configuration
reception, and recovery after app use. Those tests used a standalone macOS
CoreBluetooth bridge, not the HA ESPHome runtime. The pinned
[README](https://github.com/zuyan9/ha-dji-power-ble/blob/4682acbef33bfb9b4734818cc640f59dbd7c2758/README.md)
still labels Power 2000 as requiring model-specific testing. This is useful
support for a protocol comparison, not an equivalent long-duration reliability
benchmark for the failing installation.

## Review decisions and implementation

| Claim or proposal | Assessment | Action |
| --- | --- | --- |
| Individual setters resend unchanged `0x63` values | Confirmed code defect relative to the low-traffic design. All individual setters lacked the bulk setter's suppression. | Implemented suppression for power, limits, flags, energy mode, output tables, and charging mode. Retained bulk/tariff suppression and strengthened expired-optimistic handling. |
| Simply return when raw bytes match | Insufficient alone: the cache is optimistically updated after ACK, while device verification is separate. | Validate freshness/ranges/modes/table safety first. Coalesce pending acknowledged duplicates without calling them confirmed. Once verification expires unconfirmed, another request is allowed. |
| Write-lock wait is charged to backend timeout and can cause HA-initiated disconnect | Confirmed possible path, but zero retained GATT write timeouts in these diagnostics. It is not the demonstrated cause of the eight-second setup failures. | Separate bounded ten-second queue and backend deadlines. Queue expiry fails the request/ACK without poisoning connection health; backend timeout still recovers the same active link. Do not remove the queue deadline as the pasted example suggests. |
| ACK tasks/old writes could cross reconnect generations | Confirmed ingress and queued-write isolation gap. | Bind notifications to weak client identity/generation; validate queued writes after locking; bind scheduled ACKs to generation. Preserve the pre-disconnect setup failure phase. |
| `ble_device_callback` is deprecated and unused | Confirmed in connector 4.7.0 source and current documentation. | Removed dead callback and argument. Resolve via HA at each outer attempt; retain the connector's two-attempt limit. |
| `_find_device()` should be event-driven | Useful, low-risk improvement; one-second local history checks were not sending one GATT request per second to the station. | Keep immediate current-device lookup, then await advertisements. Preserve timeouts, exact address validation, one-shot cache fallback, and separate unexpected-disconnect gate. |
| PASSIVE should become ACTIVE | No demonstrated requirement for this exact-address wait. ACTIVE additionally requests scan responses/sweeps; it does not change authentication. | Retained PASSIVE. Reconsider if captures show necessary discovery data exists only in scan responses or fresh advertisements are being missed. |
| Drop `0x62` ACK or change `01` | A real difference from the comparison, but its correctness and effect on station load are unverified. | Retained wire behavior; request operator direction for controlled comparison. |
| Increase connection interval | API exists, but actual backend support, negotiated parameters, and DJI acceptance must be measured. | No automatic interval change. Treat as a separate experiment from application packet changes. |
| Increase/remove 30-second watchdog | It can initiate reconnects by design. No retained watchdog event explains this recovery sequence; original trigger is outside history. | Retained threshold and raw-notification criterion. Separate valid-frame/realtime age would improve a later stall-specific investigation. |
| Add traffic and congestion diagnostics | Necessary to test cumulative traffic and timeout claims on the next incident. | Added bounded command counts, completion counts, queue/backend timing and timeout splits, ACK high-water marks, skipped writes, and stale-operation rejection counts. |

Relevant primary dependency sources:
[connector 4.7.0](https://github.com/Bluetooth-Devices/bleak-retry-connector/blob/v4.7.0/src/bleak_retry_connector/__init__.py),
[connector usage](https://bleak-retry-connector.readthedocs.io/en/latest/usage.html),
[HA 2026.9.1 Bluetooth API](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/components/bluetooth/api.py).
`async_process_advertisements()` unregisters its callback through `ExitStack`
on success, timeout, or cancellation. ACTIVE mode also creates an active-scan
request. These are HA scanning semantics, not DJI recovery protocol knowledge.

## Causality and next comparison

The pasted estimates are conditional arithmetic: ten-second ACKs give 8,640
writes/day; fifteen-second SETs give 5,760/day. They are not measured totals in
the supplied files. The retained last setting ACK was over an hour before the
telemetry gap. Mini does not use the Power 2000 off-peak setting, so that setter
cannot be a universal explanation. Shared authentication, GET, push/ACK handling,
and link parameter behavior remain pertinent to both models.

The station-side cumulative-load hypothesis remains open. Neither small Python
memory usage nor successful proxy cleanup tests it. Conversely, a successful
official-app session does not by itself identify whether recovery came from a
GET, another command, a clean session boundary, or negotiated link parameters.
Previous failed HA interventions make an app-specific effect a higher-priority
field hypothesis; they do not establish a packet's identity.

**Operator decision, 2026-09-11:** option 1 was explicitly selected: preserve
current communication contents and validate the implemented robustness changes
and additional diagnostics first. Retain the legacy initial `0x60` request,
conditional `0x62` ACK and its payload, connection-parameter policy, PASSIVE
advertisement waits, and watchdog threshold. The implemented suppression of
redundant setting writes remains part of this validation. No experimental GET,
ACK-suppression, or connection-interval mode is included in this stage.

After evaluating that evidence, if a separate experimental mode is authorized,
begin with only initial GET selection: legacy request versus the
two exact comparison requests, default unchanged. Compare healthy and failed
station states and both firmware/model variants. Keep ACK policy and connection
parameters fixed. Separately capture whether DJI Home ACKs `0x62`, and compare
link negotiation and disconnect behavior. Exclude credentials/authentication
payloads from exported evidence. Do not replay unknown setting writes to test
a session-reset theory.

## Validation

New tests execute setters, cache refresh, expired verification retry, failed
ACK handling, incomplete-table rejection, queued-write timeout/cancellation,
old-generation writes/ACKs, actual notification subscription setup, a disconnect
during initial configuration, event resolution, and cancellation propagation.
No source-text-only tests substitute for these lifecycle behaviors.

Validation: **119 tests passed**, including 19 new executable regressions.
`python -X utf8 -m compileall -q custom_components tests` and `git diff --check`
passed. Pytest used an isolated cached environment with its cache provider
disabled. One obsolete release-test assertion referenced an error string inside
the never-called connector callback; it was removed while preserving the
executable fresh-advertisement and cache-rejection tests.

These tests use simulated clients and HA dependency stubs. No real-device or
elapsed-days validation is claimed, and no release/deployment has been performed.
