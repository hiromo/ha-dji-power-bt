# BLE disconnect investigation: 2026-09-11

Investigation against commit `46bce57`, integration version `0.7.31`. The supplied
DJI diagnostics also declare `0.7.31`; a deployed source hash was not supplied.
This report records an audit, not a root-cause fix or real-device validation.
This report describes the baseline before changes. Subsequent authorized
robustness changes and the comparison with zuyan9 are recorded in
[the follow-up review](ble-comparison-and-review-2026-09-11.md). No device-side
root cause has been confirmed by those changes.

## Assessment

**Operator's intended hypothesis:** "Accumulating Bluetooth load" refers to
the control/communication system inside Power 2000 and Power 1000 Mini, not to
HA or ESPHome memory/resource accumulation. The question is whether the
integration's sustained BLE session and protocol behavior gradually leave the
station in an unhealthy state. The Python retention probes below do not test
that hypothesis and must not be presented as evidence against it.

**Observed:** Power 2000 repeatedly connected and authenticated, then lost the
link approximately eight seconds later while fetching initial configuration.
This is more specific than an unavailable station or a runner that stopped
retrying. An ESPHome-side GATT error also occurred. The first triggering
disconnect is outside the retained event history.

**Inferred:** The recovery failures are consistent with a lower BLE-layer
timeout. Eight complete failing attempts took 8.018-8.072 seconds from the
`authenticated` event to the unexpected-disconnect callback. The referenced
ESPHome implementation uses an eight-second steady-state supervision timeout.
The operator tentatively identifies the proxy as `26.8.2 (ESPHome 2026.7.4)`;
the `2026.7.4` source has the same eight-second default. The exact deployed
build and negotiated connection parameters are not independently verified, so
this correspondence is not proof of the disconnect reason. Even if confirmed,
a timeout detected by the proxy would not identify the origin of the fault:
station-side loss of responsiveness remains a possible cause.

**Unknown:** Whether the initial trigger is station firmware/session state,
proxy/controller state, radio conditions, a connection-parameter interaction,
or an integration-triggered interaction between those components. A cumulative
device/proxy resource problem remains possible; the supplied evidence does not
establish one. No unbounded retention was reproduced in the exercised Python
receive and client-cleanup paths.

## Inputs and deduplication

The three DJI files all select Power 2000. Mini appears in the shared domain
history and manager summaries; these are not full Mini diagnostic exports.
The Bluetooth file is a later snapshot, not a continuous controller log.

| Alias | Supplied file suffix/type | SHA-256 |
| --- | --- | --- |
| A | DJI ` (4).json` | `5a7b7dceaad0473ea228978a2fa83823ecb021df0eb34115fe706304d4c6f108` |
| B | DJI `-1.json` | `77effa446f8dd9579878ba7085cdc2d4fd90f1d07282ecc2d585526d9c65672d` |
| C | DJI `-2.json` | `0d84b2d06f503d44581349af9743249d0f9387c338dd65b5318b8e34bf34493a` |
| D | Bluetooth diagnostic | `04da907d0ee730d468c66e51feafbcdd5b19b1d0c0bd3b56f4dbefae6bf439ba` |

Local histories contain 50 events each and domain histories 100 each. Merging
by `(event_id, monotonic_time)` produces 248 unique events, IDs 127-374,
without counting overlapping exports as separate failures. All timeline times
below are Japan Standard Time on 2026-09-11. Durations use the monotonic clock.

## Timeline

| Time | Evidence |
| --- | --- |
| 14:46:34 | Retained `last_ready_at` in A shows an earlier successful reconnection. Its preceding failure is no longer retained. |
| 14:47:04 | Last `0x61` and `0x66` before the gap, unchanged in both A and B. Last `0x62` is 14:46:55. |
| 14:48:20 | Earliest retained domain event, ID 127. The original triggering disconnect predates the retained history. |
| 14:48:21 / 14:49:30 | Attempts 7 and 8 authenticate; both disconnect during `initial_config` approximately eight seconds later. |
| 14:51:48 | Attempt 9 fails during `initial_config`: `Bluetooth GATT Error ... handle=54 error=133 description=Error`. Cleanup succeeds. |
| 14:56:49 / 15:02:00 / 15:07:09 | Attempts 10-12 authenticate, then disconnect after approximately eight seconds. Outer retry delay reaches 300 seconds. |
| 15:10:43 / 15:10:49 | Recorded integration BLE OFF / ON. The first attempt after ON still fails at 15:10:58. |
| 15:11:16 | Attempt 14 briefly reaches `ready`, having received initial configuration. It disconnects at 15:11:24. |
| 15:11:33 | B records a new authentication/notification, while the last telemetry remains 14:47:04. Thus telemetry was stale for at least 24 minutes 29 seconds. |
| 15:11:41 / 15:12:00 | Attempts 15 and 16 fail again during initial configuration. |
| 15:12:33 | Attempt 17 reaches `ready`. This remains the latest ready transition in C. |
| 15:12:49 / 15:12:58 | Mini unexpectedly disconnects, then recovers automatically in approximately nine seconds, using the same proxy source. |
| 15:26:42 | C shows current Power 2000 `0x61` and `0x66`, with both managers ready. The exact first resumed telemetry timestamp is not retained. |

The operator reports that HA BLE was turned OFF before the successful Android
DJI Home connection. DJI Home then displayed all Power 2000 information
normally, was used for approximately one minute, and was closed. The operator
reports HA BLE OFF/ON promptly afterward; a brief connection and another
disconnect were seen before unattended recovery. The recalled Android time might be late in the
15:00 hour, but the operator explicitly considers that estimate unreliable.
The exports contain no Android timestamps, so the Android session cannot be
unambiguously matched to the retained OFF/ON events. The recorded OFF/ON was
followed by approximately 104 seconds of further recovery attempts before the
final Power 2000 ready transition. The sequence resembles the reported behavior,
but does not establish that OFF/ON alone reset the underlying fault.

## What the Bluetooth snapshot establishes

**Observed:** HA is `2026.9.1`, using an `ESPHomeScanner` on an Olimex ESP32 PoE
proxy. No local Bluetooth adapter appears in D. Both DJI stations share this
source. Allocations report four slots, two free, and one allocated to each
station. Scanning is running; AUTO currently selects PASSIVE.

Correlating D's monotonic timestamp with C's event timestamps places D at
approximately **16:31:51 JST**, assuming the same HA clock/runtime. It must not
be treated as a measurement of free slots at the initial failure. Scanner totals
of 180 completed and seven failed connections include other integrations and
have a different scope from DJI manager counters.

No retained DJI event reports `out_of_slots`, a fresh-advertisement timeout, a
failed notify subscription, or a GATT write timeout. The maximum observed domain
lock wait is about 55 microseconds. Every retained `disconnect_complete` reports
`ok`; the disconnected clients report false afterward. These observations argue
against the corresponding failure modes in this retained window, not against
all historical controller resource failures.

## Cause candidates

### 1. Station/proxy BLE interaction: highest investigation priority

Eight failures show unusually consistent elapsed time after authentication:

| Attempt | Authentication to unexpected-disconnect callback (seconds) |
| ---: | ---: |
| 7 | 8.072 |
| 8 | 8.038 |
| 10 | 8.061 |
| 11 | 8.037 |
| 12 | 8.018 |
| 13 | 8.025 |
| 15 | 8.033 |
| 16 | 8.032 |

The integration's notification watchdog is 30 seconds and GATT write timeout
is 10 seconds; neither explains this eight-second interval. The callback occurs
before the integration requests cleanup in these eight cases.

ESPHome `2026.7.4` defines `MEDIUM_CONN_TIMEOUT = 800` in units of 10 ms and
uses medium parameters for cached connections and after service discovery.
That source also specifies preferred intervals of 8.75-11.25 ms. These are
reference defaults, not measured parameters on the user's proxy.
[Parameter definitions and connection setup](https://github.com/esphome/esphome/blob/2026.7.4/esphome/components/esp32_ble_client/ble_client_base.cpp).

Error 133 is `0x85`, the generic `ESP_GATT_ERROR`; it does not specifically mean
memory exhaustion, a leaked slot, or authentication failure. The ATT handle 54
must be mapped from the actual GATT database before naming its characteristic.
[Espressif error definitions](https://github.com/espressif/esp-idf/blob/v5.5.1/components/bt/host/bluedroid/api/include/api/esp_gatt_defs.h).

Android success weighs against a station whose entire Bluetooth subsystem is
permanently dead. It does not distinguish proxy problems from central-specific
station/session/parameter behavior. HA was disabled during the reported Android
session, so simultaneous HA retries competing with that session should not be
used to explain this observation. The recovery sequence changes several things:
HA teardown, a pause in HA connection attempts, Android initialization/data
exchange, and Android disconnection. Their individual effects are not isolated;
Android's success does not by itself prove that Android reset the fault.
Mini's later disconnect supports checking
the shared path, but its different timestamp and successful recovery do not
prove a simultaneous proxy reboot or the same failure mechanism.

### 2. Configuration transfer after authentication: targeted comparison

The failure stage repeatedly follows authentication and the initial `0x60`
request. In these files, the request payload is 48 bytes (61-byte DUM frame),
the successful response payload 357 bytes (370-byte frame). Authentication
success alone therefore does not validate subsequent configuration transfers.

**Hypotheses:** connection parameters, negotiated MTU/fragment handling, station
session initialization, or a controller fault manifesting during the first
configuration exchange. A safe TX record is created before acquiring the write
lock and completing `write_gatt_char`, so `tx_0x60` is not proof that the write
completed or that its response started arriving. There is no MTU, per-write
completion timing, ATT reason, or notification-length history to distinguish
these hypotheses. Changing write mode, fragmenting frames, or inserting a delay
without such evidence would be speculative.

### 3. Station-side accumulation under sustained integration use

**Hypothesis, matching the operator's clarification:** sustained integration
use gradually stresses or leaves stale state in the station's control or
communication system. The station's firmware implementation, internal queues,
memory usage, and division of responsibilities between controllers are unknown.
Do not assign this specifically to the BMS, a particular MCU, or a shared
firmware implementation across the two models without evidence.

Candidate mechanisms and the integration paths to compare are:

| Station-side hypothesis | Relevant integration behavior | Evidence needed |
| --- | --- | --- |
| Notification generation or transmit-state cleanup accumulates resources during a long session. | Persistent C305 subscription, with sustained `0x61`/`0x66` and configuration reports. | Compare time-to-failure under controlled continuous-session conditions; retain notification timing before the first failure. Python replay does not exercise the station's transmitter. |
| Application ACK/session behavior differs from what station firmware expects over long operation. | Qualifying `0x62` gets a same-sequence `0x80` ACK with payload `01`; initialization uses authentication followed by `0x60`. | Compare non-secret command metadata, ACK latency, and initialization/termination behavior with DJI Home. No missing keepalive, incorrect ACK, or required termination command has been established. |
| Repeated initialization leaves or aggravates stale station session state after the first fault. | Each recovery creates a connection, authenticates, and requests initial configuration. A brief ready transition resets backoff. | Compare matched HA-disabled rest intervals with and without Android use, and retain per-attempt outcomes. Existing backoff already limits retry frequency; this is not evidence of an unrestricted retry flood. |

Android's successful session after HA was disabled is compatible with this
hypothesis: HA teardown, the quiet interval, or Android's different session
exchange might release or bypass station state left by the prior session.
It establishes that the station could serve Android at that later time, not
that the station was healthy throughout the preceding HA failure. No one of
those possible recovery mechanisms is confirmed.

The reported recurrence on both models makes their common BLE operating
conditions worth comparing before assigning the issue to Power 2000 Energy
Saving writes. An hour without a setting write before the telemetry gap weakens
an immediate-write trigger, but cannot exclude accumulation caused by earlier
writes or by the continuing session.

### 4. Scope of the HA-side retention and traffic checks

Ordinary telemetry does not poll every second: `0x61` and `0x66` are pushed by
the station, and neither triggers an application ACK. Only qualifying `0x62`
reports schedule ACKs. Raising the HA telemetry publication interval reduces
entity updates, not radio traffic or notification parsing.

The retained final pre-gap setting ACK is at 13:40:15, over an hour before the
last telemetry. In A, config reads total 77 since manager setup, cache hits 608,
and verification readbacks zero. Pending ACKs and verification tasks are zero;
there is no write-lock holder or write timeout. The active client and retired
client are both absent in A, and expected-disconnect records are zero. These
are not signs of an application queue or owned-client backlog at that snapshot.

Safe latest payloads replace a bounded command/direction set; capture, connection
history, write history, and HMS patterns are bounded. The 158,838 HMS fast-path
hits in A/B are a counter, not 158,838 retained reports. The next local request
sequence has advanced only from the initial 10,001 to roughly 10,840; inbound
telemetry and `0x62` ACKs do not advance it. There is no evidence of a local
request-sequence wrap at this failure.

Continuous GATT connections still consume controller scheduling resources even
at low application byte rates. These checks cannot exclude a leak, congestion,
or firmware problem inside the station, ESP32 stack, or real HA dependencies.
Low application traffic volume also does not prove correct station-side resource
release. The local probes are ancillary checks of integration bookkeeping, not
an assessment of the operator's station-side accumulation hypothesis.

## Code findings and reproducible limitations

These findings must not be promoted to the cause of the initial disconnect.

| Finding | Location | Classification and impact |
| --- | --- | --- |
| Notification ingress is not tied to its originating client/generation. Both subscriptions receive the same bound `_on_notify`. | `manager_connection.py:339,382`; `manager_transport.py:32,47` | **Confirmed by synthetic lifecycle execution:** a saved old subscription callback changes telemetry after disconnect and feeds the new generation's reassembler after reconnect. Pending dictionary generation keys alone do not identify an incoming callback's origin. A response collision additionally requires matching sequence/command; none is established in these files. |
| The watchdog accepts any notification bytes, including malformed input or HMS without realtime metrics. | `manager_transport.py:32`; `manager_connection.py:1221` | **Confirmed by execution:** after setting receive age to 120 seconds, feeding one invalid byte changes health from watchdog failure to healthy while no new telemetry was parsed. This can conceal a partial data stall, but does not explain the observed eight-second physical disconnects. |
| Setup failure phase is overwritten by the disconnect callback. | `manager_connection.py:432,935` | **Confirmed by execution and events:** `disconnect_callback.phase = initial_config`, followed by `connect_attempt_failed.failure_phase = idle`. Capture the pre-reset phase when diagnosing this failure; `idle` is not its actual setup stage. |
| Backoff resets as soon as initial config succeeds, before sustained telemetry is established. | `manager_connection.py:265,417` | **Observed in attempt 14:** brief ready resets the retry progression, despite telemetry still being stale. This can amplify a flapping recovery cycle; it does not initiate a long-running link failure. A future stability criterion should preserve the documented meaning of `ready`. |
| Stale-connection cleanup does not reset the ESPHome proxy. | `manager_connection.py:665` | **Confirmed upstream scope:** the connector helper resolves local BlueZ devices and returns when none exists. The counter increments when the call returns, including a no-op. Three counted calls are not proof that proxy internals were reset. |

The generation statement in the transport/architecture documentation describes
the intended isolation guarantee. The current implementation lacks the ingress
identity check needed for that full guarantee. This audit records that gap
explicitly; any implementation correction needs client-bound callback behavior
tests and corresponding contract updates.

HA `2026.9.1` declares `bleak-retry-connector==4.7.0` and
`bleak-esphome==4.0.0`. The latter removes notification registrations and client
tracking during disconnect cleanup, so the synthetic late-callback test does
not prove that its normal path actually delivers late callbacks. Its teardown
also has its own settling behavior; our three-second outer disconnect timeout
can interrupt a slower backend, although all retained cleanup results here are
successful.
[HA Bluetooth requirements](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/components/bluetooth/manifest.json),
[HA ESPHome requirements](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/components/esphome/manifest.json),
[BlueZ cleanup helper](https://github.com/Bluetooth-Devices/bleak-retry-connector/blob/v4.7.0/src/bleak_retry_connector/__init__.py),
[ESPHome client cleanup](https://github.com/Bluetooth-Devices/bleak-esphome/blob/v4.0.0/src/bleak_esphome/backend/client.py).

## Local validation

- Full existing suite: **100 passed** using Python UTF-8 mode and pytest with
  its cache provider disabled. `compileall` passed for `custom_components` and
  `tests`. Initial test-environment failures were missing pytest/aiohttp and
  Windows cp932 decoding; an isolated dependency environment and UTF-8 mode
  resolved them without changing production code.
- Replayed the supplied C `0x61`/`0x66` payloads through the real framing,
  reassembly, parsing, payload bookkeeping, and publication scheduling paths:
  **200,000 pairs / 400,000 frames** in about 30 seconds. Latest payload entries
  remained 2, HMS history 1, capture 0, pending requests 0, ACK tasks 0, and
  buffered bytes 0. GC-tracked objects were 18,577 at 10,000 pairs and 18,575
  at both 100,000 and 200,000 pairs. HMS full parse count was 1 and fast-path
  hits 199,999. This is an accelerated retention probe, not elapsed-days testing,
  a complete process-memory profile, or a test of real entity/backend load.
- Executed **10,000** unexpected-callback/setup-abort cleanup cycles using
  synthetic clients: live clients in a weak set 0 after GC, expected callback
  records 0, retired client absent, retained events capped at 50.
- Executed the real subscription setup path with fake backend clients, saved the
  first callback, disconnected, and established a second connection. Invoking
  the saved callback changed receive state and added a frame to generation 2.
- Injected one invalid byte after a synthetic 120-second receive gap; watchdog
  failure disappeared. Executed a disconnect during initial config; callback
  phase was `initial_config`, while the final failure phase was `idle`.

No commands were sent to either station, no HA configuration was changed, and
no authentication payloads were captured or copied into this repository.

## Next evidence and bounded follow-up work

The primary behavioral comparison should target the station-side hypothesis
above. Proxy lifecycle logs are useful for observing the link's failure mode;
requesting them does not presume that the proxy is the component at fault.

1. Verify the tentative `26.8.2 (ESPHome 2026.7.4)` build identification and
   obtain the proxy's ESP-IDF version and configuration. During
   the next event retain proxy lifecycle logs, especially disconnect reason,
   CLOSE/DISCONNECT events, negotiated interval/latency/supervision timeout,
   MTU, GATT errors, heap minimum, and largest free block. Prefer lifecycle
   metadata; do not enable unrestricted authentication/payload dumps.
2. Preserve the **first** disconnect and a small per-generation summary before
   replacing the reassembler. Current zero CRC/discard counters after reconnect
   cannot rule out corruption on the discarded previous connection. Record raw
   notification age, valid-frame age, and realtime age separately; record
   initial-config TX completion and RX timing without secret payloads.
3. Correct client/generation checks at notification ingress and after acquiring
   the write lock; retain the true failure phase; verify cancellation/cleanup
   paths with backend-shaped behavior tests. These are robustness changes, not
   evidence that the eight-second fault is fixed.
4. Compare a failing station through an already available alternative central
   or proxy, while releasing the previous central first. Separately compare
   one versus two persistent DJI connections on the shared proxy. Reset only
   one component per experiment and record the time, to distinguish station
   state from proxy state and concurrent-link behavior.
5. Compare Android and HA initialization and negotiated transport metadata if
   the fault remains. The operator reports normal display of all information;
   for a controlled comparison, retain timestamped value changes. Compare the
   same roughly one-minute HA-disabled interval followed by HA re-enabling
   without using Android, to separate the effect of HA teardown/rest from an
   Android-specific exchange. Test reduced setting-write activity separately from
   notification reception; changing HA publication throttling does not isolate
   BLE traffic. Keep fresh-advertisement gating, retired-client cleanup, weak
   references, and the shared lifecycle lock intact during these experiments.
