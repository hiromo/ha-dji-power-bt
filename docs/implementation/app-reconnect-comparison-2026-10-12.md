# DJI Home versus HA reconnect traffic (2026-10-12 analysis)

Historical comparison below describes source `9da3acf`. A subsequent explicit
operator decision adopted the observed startup order; current behavior is in
[bluetooth-lifecycle.md](bluetooth-lifecycle.md). The implementation now uses
the 61-byte request and first-report/ACK barrier. The original comparison and
test results below are retained as historical evidence, not current behavior.

## Conclusion and scope

**Observed:** the supplied Power 1000 Mini HA diagnostic repeatedly reaches
successful authentication, then disconnects during `initial_config`. DJI Home
uses a different configuration GET payload and initialization order. These are
concrete investigation candidates, not proven causes. No runtime behavior is
changed by this analysis.

The operator reports that DJI Home can connect when HA cannot, particularly on
Mini. Preserve this report separately from timestamp-confirmed evidence:

- Android capture: 2026-10-09 08:03:17–08:07:12 JST.
- HA Mini's retained recent failures: October 10 around 11:02–11:05 JST.
- HA Power 2000: ready since October 9 at 08:10:41 JST, still receiving data
  on October 10 at 11:06:42 JST.

These files do not provide a synchronized failed-HA/successful-app pair, or
prove that an app operation repaired the HA failure shown here. Both diagnostics
identify integration 0.7.32 and HA 2026.10.0. Comparison source is commit
`9da3acf`; its GET literal exactly matches the diagnostics' TX payloads.
Firmware agrees between app and HA: Mini `01.00.0300`, Power 2000 `01.00.1500`,
communication module `03.03.0000`.

Sources: operator-supplied two DJI config-entry diagnostics, ESPHome diagnostic,
and `dji_power_bluetooth_codex_export.zip`. Frame references below use exported
`original_first_frame`; for fragmented DUM frames, the reply reference denotes
the ATT message completing the frame. Identifying source data and authentication
payloads are not retained in this document or new diagnostic artifacts.

## HA failure evidence

Mini's two complete retained recent attempts show:

| JST on October 10 | Attempt 26 | Attempt 27 |
|---|---|---|
| Fresh advertisement, GATT, C305 subscription | 11:03:35 | 11:05:47 |
| Authentication succeeds | 11:03:36 | 11:05:48 |
| Unexpected disconnect during initial configuration | 11:03:44 | 11:05:56 |

Attempt 25 also ends in `initial_config`, but its beginning is outside the
50-event local history. Latest GET TX is sequence 10066 at 11:05:48; retained
GET RX is sequence 10051 at 10:54:24, from an earlier successful connection,
not a reply to that request. Latest 0x62 is from 10:58:52.

Runtime totals: 22 GATT adoptions, 21 GATT reconnects, seven successful
reconnects, five consecutive failures, current 300-second backoff. All 22 GET
backend writes completed; write-lock/backend-write timeouts are zero. Backend
completion is not proof of device acceptance. No active, retired, or expected
disconnect clients remain. Reassembly counters are zero after cleanup/reset;
they cannot establish absence of earlier receive errors.

**Inferred:** discovery, slot acquisition, subscription, and pair-key rejection
are weaker explanations for these attempts than a post-authentication problem.
The callback precedes the normal 10-second request timeout. HA does not retain
the HCI disconnect reason, so the initiator and root cause remain unknown.

Power 2000 has one GATT adoption and zero reconnects in this manager runtime.
Its old error is `No connectable Home Assistant Bluetooth scanner is available`
at startup, followed by successful initialization. This diagnostic contains no
Power 2000 post-authentication reconnect failure.

ESPHome 2026.7.4 reports available/scanning, three free of four slots, no connect
in progress, 214 completed and two failed connects. This does not support current
slot exhaustion or prove a leak; it cannot exclude earlier transient proxy,
radio, or controller trouble. Counts are not exclusively DJI operations.

## Android sessions and validation

The captured order includes Power 2000 before Mini, then Power 2000 again:

| Model/session | Start (October 9 JST) | Outcome |
|---|---|---|
| Power 2000/1 | 08:03:41.521, frame 1490 | Authentication/GET success; disconnect 08:04:02.725, frame 2939, reason byte 0x16 |
| Mini/1 | 08:03:58.858, frame 2288 | Disconnect 08:03:59.175, frame 2346, reason byte 0x3E; no ATT exchange |
| Mini/2 | 08:03:59.744, frame 2434 | Authentication/GET success; disconnect 08:04:19.309, frame 3805, reason byte 0x16 |
| Power 2000/2 | 08:04:15.390, frame 3278 | Authentication/GET success; notifications continue, no disconnect retained |

The app also experiences a short failed Mini link before success. Mini's
successful sample lasts about 20 seconds, not a long-duration stability test.
It includes six GET replies, 15 telemetry frames, 15 HMS frames, two reports,
and two report ACKs.

Session/direction-separated C304/C305 streams were fed into the repository's
`DumlReassembler`: Mini 52 frames, Power 2000 455 frames; zero CRC, length,
discard, partial-timeout, or trailing-buffer errors. All 18 app GET frames
rebuild byte-for-byte with the existing builder using their sequence/payload.
The comparison accounts for DUM frames spanning ATT notifications.

The native device-specific btsnoop records also match their packet JSONL bytes
exactly: 754 Mini records and 831 Power 2000 records. This checks export
consistency; the original unfiltered Android source was not supplied here.

## Matches and differences

| Layer | DJI Home | Integration |
|---|---|---|
| GATT | C304 value handle 0x0036, C305 value 0x0038, notify CCCD 0x0039 | Same UUIDs; backend resolves handles |
| Write method | ATT Write Request (0x12), including ACKs | `response=True` |
| Envelope | Version 1, sender 0x02, receiver 0xAB, request type 0x20, response type 0x80 | Matches; builder reproduces app GETs |
| Authentication | Two session-material requests, then key authentication | One session-material request, then key authentication |
| Initial GET timing | First 0x62 received/ACKed before first GET in all successful sessions | GET immediately after authentication; no first-report barrier |
| Broad GET | 61-byte payload, twice with distinct sequences | 48-byte payload, once |
| Additional GETs | `00 01 10` twice, then `00 04 10` twice | Not sent during initialization |
| 0x62 ACK | Same sequence, type 0x80, payload `01` | Matches |
| Other initial write | Power 2000: 0x63 containing 0x100E and 0x1023; Mini: absent | No equivalent initialization write |

The app's two session replies contain different session material; final
authentication uses the second reply with HA's same structural format. All
authentication responses succeed. This does not establish that requesting
session material twice is necessary: HA authenticates in the failed attempts.
Authentication bytes and keys were compared only in memory, never exported.

All 22 observed reports are ACKed (Mini two, Power 2000 twenty). Removing ACKs
would move away from this app evidence.

Android negotiates MTU 517 in all successful sessions. Connection updates reach
48.75 ms interval, zero peripheral latency, 5,000 ms supervision timeout. The
capture also includes service discovery and a descriptor write at handle 0x0004.
HA diagnostics lack comparable negotiated parameters/full ATT setup traffic.
Their absence is not evidence of a mismatch. The filtered export excludes some
generic controller traffic; it is not a complete lower-layer setup trace.

### GET payload and grammar

**Observed:** the app's 61-byte broad request, grouped into one byte plus pairs:

```text
00 | 0010 0210 0310 0510 0610 0710 0810 0910 0a10 0b10
     0c10 0d10 0e10 1510 1610 1810 1910 1b10 1c10 1d10
     1e10 2010 2110 2210 2310 2410 2510 2610 2710 2810
```

**Inferred grammar:** operation byte plus little-endian 16-bit selectors.
The app has 30 complete selectors, beginning with 0x1000. HA has 23 complete
selectors plus unmatched byte `25`; the likely intended last selector 0x1025
lacks its high byte `10`. Relative to HA with that byte restored, the app also
includes 0x101C, 0x101D, 0x1021, 0x1026, 0x1027, and 0x1028.

This strengthens the previously recorded missing-byte hypothesis. It does not
prove that malformed-tail handling causes disconnects or that adding the byte
fixes recovery. The same 48-byte HA request has succeeded on both models.

Mini broad requests at frames 3120/3123 receive matching 298-byte replies at
3126/3134. First reply completion is about 138 ms after the request; the second
request was already sent, so duplicates need not be failure-driven retries.
Mini's four subsequent short replies are 24 bytes each, not equivalent broad
configuration snapshots. Power 2000 broad replies are 357 bytes, short replies
79 and 24 bytes. All match sequence/type expectations of HA's response router.

### Timing and other writes

Mini authentication completes at 08:04:03.707, first 0x62 at 08:04:04.146,
ACK TX at 08:04:04.158, first GET at 08:04:04.305: approximately 598 ms after
authentication and 147 ms after ACK TX. Power 2000 authentication-to-GET delays
are approximately 110 and 702 ms. Order alone does not prove an explicit app
wait: UI scheduling or other initialization might produce the same order.

**Hypothesis:** immediate HA GET may interact with a device initialization race;
processing the first report before GET may help. No required delay is proven.

Power 2000's extra 0x1023 write has unresolved semantics. It is not a demonstrated
reset command and cannot explain Mini success without it. Do not copy this
write or its identifying companion into recovery logic.

## Controlled follow-up experiments

1. Retain synchronized Mini failure/retry events and proxy/controller logs,
   followed by an app session and HA retry. Record negotiated MTU, disconnect
   reason, first-report timing, and evidence of GET delivery. Continue excluding
   authentication from safe capture.
2. Compare the retained GET with only final `10` appended; keep ACKs, timing,
   sequence handling, and reconnect gates unchanged. This separates tail
   completeness from the app's six additional selectors.
3. Separately compare the exact 61-byte app request, then a bounded first-report
   wait if needed. Do not change payload, pacing, duplicate requests, and
   authentication simultaneously.
4. Preserve broad configuration reads; Mini's short replies are not substitutes.
   Validate merge/completeness and unknown-record safety before any multi-read
   initialization is allowed to support writes.
5. Repeat multiple failure/recovery cycles and sustained operation on Mini,
   then Power 2000. Initial success alone is insufficient.

These are proposed experiments, not device operations performed here. No
agent-operated real-device validation was performed.

## Repository validation

Only this report and related protocol documentation were changed. Full pytest
with Windows UTF-8 mode completed: 254 passed, six failed. Five failures are in
unchanged `automations/power2000_v7_8c_specs/test_control.py` budget/control
expectations; one flags existing non-English text in unchanged
`docs/protocol/hms-codes.md`. They are outside this packet comparison.
`compileall` for `custom_components` and `tests`, and `git diff --check`, passed.
The sandboxed test run stalled in Windows asyncio socketpair initialization;
the completed run used ordinary local execution permissions and UTF-8 mode.
