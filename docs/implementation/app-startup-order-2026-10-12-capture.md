# October 12 Android capture: startup report order is not fixed

## Evidence and extraction

The operator supplied a new Android H4 btsnoop while reporting HA reconnect
failure and successful DJI Home access. Source range: October 12,
19:07:35.438–19:11:56.023 JST. SHA-256:
`ca09f599ef21ce76782e396687ad5ca6beda383fba470fbd2cff6e9af78e557b`.

**Observed:** 9,680 HCI records, cumulative drops field zero; exact-address and
connection-handle lifetime filtering selects 1,509 records, 774 ATT messages,
and 521 DUM frames. Reviewed Python stdlib H4/ACL/ATT helpers and the repository
DUM reassembler were used. Session/direction-separated streams have zero CRC,
length, discard, partial-timeout, or trailing-buffer errors. Android HCI is not
an over-the-air capture and does not prove RF-level losslessness.

Private local outputs include Wireshark-compatible device captures, frame maps,
timeline CSV and counts. Eighteen authentication ACL records were omitted from
exports; keys/authentication bytes were inspected only in memory. Other device
identifiers remain in the private filtered captures, outside the repository.
Generic controller-global traffic is excluded; consult the original for full
context. Frame numbers below refer to the original, not renumbered filtered
files. A fragmented DUM frame's reference/time identifies its completing ATT
message. No runtime code was changed in this investigation.

## Sessions

| Device/session | Established (JST) | Observed end |
|---|---|---|
| Mini/1 | 19:08:01.568, #2140 | 19:08:16.949, #3349, reason byte 0x16 |
| Power 2000/1 | 19:08:16.715, #3266 | 19:08:29.616, #4400, reason byte 0x16 |
| Mini/2 | 19:08:25.712, #3897 | Notifications through 19:11:56.023; no disconnect retained |

All three authenticate and complete six GETs. Mini/2 provides over three minutes
of continued telemetry. User-reported HA failure is context; the preceding HA
snapshots and this Android capture are not a simultaneous same-radio comparison.

## Decisive counterexample: Mini/1

| JST | Source frame | Direction | Operation |
|---|---:|---|---|
| 19:08:04.482 | 2660 | TX | C305 notification enable |
| 19:08:04.633–19:08:05.005 | 2663–2703 | Both | Two session requests/replies |
| 19:08:05.035 | 2712 | TX | Key authentication |
| 19:08:05.200 | 2740 | RX | Successful auth response |
| 19:08:05.250 | 2750 | RX | First 0x61, 99-byte payload |
| 19:08:05.270 | 2751 | TX | First 61-byte GET, sequence 10009 |
| 19:08:05.298 | 2752 | RX | First 0x66 |
| 19:08:05.354 | 2756 | TX | Second broad GET, sequence 10010 |
| 19:08:05.400 / .591 | 2759 / 2765 | RX | Broad replies, 298 bytes each |
| 19:08:05.499–.844 | 2764–2775 | TX | 0x1001 twice, 0x1004 twice |
| 19:08:05.982 | 2781 | RX | Last short GET reply |
| 19:08:06.078 | 2784 | RX | First 0x62, sequence 4161, 319 bytes |
| 19:08:06.101 | 2785 | TX | Report ACK |

**Observed:** GET starts 19.5 ms after first telemetry, 808.6 ms before the
first configuration report. All six GETs finish before that report. Neither
first 0x62 nor first 0x66 is a universal prerequisite for starting app GETs.
This does not prove GET triggers reporting; periodic delivery could explain it.
Mini/1's second report near session end has no corresponding retained ACK.

## Preceding notifications across all successful sessions

GET TX minus first notification completion, milliseconds. Positive means the
notification arrived first; negative means GET was sent first.

| Capture / session | 0x61 | 0x62 | 0x66 |
|---|---:|---:|---:|
| October 9 Mini/2 | +157.8 | +159.0 | +156.8 |
| October 9 Power 2000/1 | +104.2 | +106.4 | +103.9 |
| October 9 Power 2000/2 | +163.2 | +165.8 | +72.0 |
| October 12 Mini/1 | +19.5 | -808.6 | -28.1 |
| October 12 Power 2000/1 | +55.5 | +151.1 | +54.2 |
| October 12 Mini/2 | +15.7 | +259.4 | +13.4 |

**Inferred candidate:** receiving first valid telemetry may initiate the app's
GETs, or a common readiness event may schedule both. These correlations do not
prove an explicit 0x61 wait or reveal app callback/UI logic.

Mini's first 0x61 bodies in the two new sessions are byte-identical after the
16-byte header; only header offsets 4 and 5 differ. Both decode as 97% SoC,
raw battery status 2 and 27.8 C. No content flag selecting startup order was
identified. The same physical Mini exhibits both orders, so a fixed model
branch is not justified by this trace.

## Packet contents and transport comparison

- Two session requests followed by key authentication remain unchanged; the
  second session reply's material is used. All three auth responses per session
  have status zero and five bytes. No extra mode-selection command was observed.
- Every broad GET exactly matches the October 9 61-byte request. Two are sent
  per session, with byte-identical response bodies after the 20-byte prefix.
  Mini replies have 298 bytes; Power 2000 replies have 357.
- `00 01 10` and `00 04 10` still occur twice each. Mini replies are 24 bytes
  each; Power 2000 replies are 79 and 24 bytes. These remain targeted reads.
- Power 2000 again sends a 39-byte 0x63 in the same initialization position;
  Mini does not. Its semantics remain unresolved.
- ATT Write Request (0x12), C304/C305 handles, and MTU 517 match the older
  capture. Link updates reach 48.75 ms interval, zero latency, 5,000 ms
  supervision timeout. No notifications on another characteristic were found.
  These are Android parameters, not verified HA/proxy parameters.
- Requests can overlap at the application-response level: Mini/1's second
  broad GET precedes its first reply; short reads can start before the second
  broad reply. HA serializes requests. Identical payload/order does not imply
  identical scheduling or controller behavior.

Mini/2's last 0x62 is at 19:09:20.509, ACK TX at 19:09:21.329. Telemetry and
empty HMS continue through 19:11:56.023, 155.5 seconds after the report. Thus
an approximately ten-second 0x62 cadence is not a universal liveness guarantee.

## Implications and next experiments

The earlier October 12 HA snapshots show Mini authenticating then disconnecting
roughly eight seconds later without GET in recent attempts, while Power 2000
successfully recovered once. HA's HCI disconnect reason remains unknown.

**Observed contradiction:** ADR 0008's mandatory first-0x62 barrier matches the
older three app samples but excludes the new successful Mini/1 sequence. This
is a known implementation limitation. It is not proven to be the only cause:
historical immediate-GET attempts also failed and Android/proxy transport differs.

A future readiness policy should consider report-first and telemetry-first
arrival, acknowledging required reports even when they arrive during GETs.
The no-report/no-telemetry case needs a separate bounded fallback experiment;
no successful sample here establishes that behavior. A first-0x61 trigger, a
short post-authentication delay, and overlapping app requests are separate
**Hypotheses**, not interchangeable fixes. No state flag or mandatory model
split has been established. Retain generation isolation, request matching,
bounded waits and existing recovery safeguards when testing alternatives.

Synchronized proxy HCI/error evidence and repeated same-state captures are
needed before claiming recovery is solved. Do not copy unknown writes or add
authentication logging. This investigation leaves runtime behavior unchanged.
