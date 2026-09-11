# BLE implementation comparison and proposed-change review: 2026-09-11

This follows the [incident investigation](ble-disconnect-investigation-2026-09-11.md)
and compares local baseline `46bce57` (`0.7.31`) with
`zuyan9/ha-dji-power-ble@4682acbef33bfb9b4734818cc640f59dbd7c2758` in a
temporary checkout. No hardware or HA instance was operated.

Earlier HA-side actions reportedly did not clear similar faults. Here, with HA
BLE disabled, DJI Home displayed all data for about one minute before HA later
recovered. This prioritizes an official-app station-state effect without
identifying a packet or excluding Android link negotiation/teardown; the app
time cannot be matched to one diagnostic event. The pasted AI review supplied
claims, not measured traffic or verified mainboard/inverter errors.

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

**Synthetic confirmation:** with normalized sequences and synthetic credentials,
both builders produced identical authentication frames. A fake GATT backend used
seven-byte notification fragments. Initial GET payload/frame lengths were
`48/61` here and `3/16, 3/16` there; one valid `0x62/0x40` produced one ACK here
and none there. This establishes code differences, not hardware compatibility or
repair, and exported no authentication payload.

The GET difference is the first initialization comparison candidate because the
retained failures follow authentication during initial configuration. Content
matters: both implementations already send a 51-byte authentication frame, so
the logs contradict a generic failure above 20 bytes. MTU, long-write behavior,
station processing, and the legacy GET's field boundaries remain unmeasured; see
[unknowns](../protocol/unknowns.md#configuration-get-grammar-and-recovery).

The comparison has no extra reset, session-finalization, keepalive, or report
subscription command; DJI Home may still have one. Its original Power 1000
encrypted transport is model-specific and unused for Power 2000/Mini.

Limited external evidence in [Mini issue #4](https://github.com/zuyan9/ha-dji-power-ble/issues/4)
reports about ten reconnects over two days, successful report/configuration
reception, and recovery after app use on a standalone macOS CoreBluetooth bridge,
not HA ESPHome. The pinned
[README](https://github.com/zuyan9/ha-dji-power-ble/blob/4682acbef33bfb9b4734818cc640f59dbd7c2758/README.md)
still requires Power 2000-specific testing, so this supports protocol comparison
rather than equivalent long-duration reliability.

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
`async_process_advertisements()` unregisters through `ExitStack` on success,
timeout, or cancellation; ACTIVE also requests active scanning. These are HA
scan semantics, not DJI recovery knowledge.

## Causality and next comparison

The pasted 8,640 ACK/day and 5,760 SET/day estimates are conditional arithmetic,
not measurements. The last retained setting ACK preceded the telemetry gap by
over an hour, and Mini lacks the Power 2000 off-peak setting. Shared
authentication, GET, push/ACK, and link parameters remain relevant.

The station-side cumulative-load hypothesis remains open: Python memory and proxy
cleanup do not test it. DJI Home success cannot distinguish a GET, another
command, a clean boundary, or link parameters. Earlier failed HA interventions
raise the priority of an app-specific effect without identifying its packet.

**Operator decision, 2026-09-11:** option 1 was explicitly selected: preserve
current communication contents and validate the implemented robustness changes
and additional diagnostics first. Retain the legacy initial `0x60` request,
conditional `0x62` ACK and its payload, connection-parameter policy, PASSIVE
advertisement waits, and watchdog threshold. The implemented suppression of
redundant setting writes remains part of this validation. No experimental GET,
ACK-suppression, or connection-interval mode is included in this stage.

If later evidence justifies an experimental mode, vary only the initial GET:
legacy versus the two exact comparison requests, default unchanged. Compare
healthy/failed states and both models/firmwares while fixing ACK and connection
parameters. Separately compare DJI Home's `0x62` ACK, link negotiation, and
disconnect. Exclude credentials/authentication payloads and do not replay unknown
setting writes.

## Validation

Nineteen new executable regressions cover setters, cache/verification behavior,
ACK failure, incomplete tables, write timeout/cancellation, old generations,
notification setup, initial-config disconnect, event resolution, and cancellation.
The full **119-test** suite, `compileall`, and `git diff --check` passed. An obsolete
source-text assertion for the unused callback was removed while executable cache
and fresh-advertisement tests remain.

Tests use simulated clients and HA dependency stubs; no real-device or elapsed-
days validation is claimed. The resulting changes were released as `v0.7.32`.
