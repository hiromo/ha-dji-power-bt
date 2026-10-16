# Command set and command behavior

The implemented application command set is `0x5A`.

## Command summary

| Command | Direction/role | Current meaning | Status |
|---|---|---|---|
| `0x60` | request/response | configuration/status read | Confirmed |
| `0x61` | unsolicited notify | realtime telemetry | Confirmed |
| `0x62` | unsolicited notify/report | configuration/state report; may require ACK | Confirmed |
| `0x63` | request/response | configuration write and per-property result | Confirmed |
| `0x66` | unsolicited notify | HMS/auxiliary status | Structure observed; semantics provisional |
| `0x6A` | request/response | local pair-key authentication | Confirmed |

## 0x60 configuration read

The manager uses the exact 61-byte `DEFAULT_STATUS_REQUEST_PAYLOAD` observed
from DJI Home on both Power 2000 and Power 1000 Mini. It fits an operation byte
`00` followed by 30 little-endian selectors (**Inferred** grammar). See the
[wire comparison](../implementation/app-reconnect-comparison-2026-10-12.md)
for exact bytes. It replaces the historical 48-byte literal, whose incomplete
final selector remains a hypothesis for earlier reconnect trouble.

At initial connection and every reconnect, after authentication the manager
reads the broad request once without waiting for 0x62,
then reads `00 01 10` twice and `00 04 10` twice. Each request has a new sequence
and waits for its matching response before the next request. Only the short
reads remain duplicated as observed in the app. By operator
decision on 2026-10-16, all models use one broad read to reduce duplicate
startup traffic; improved disconnect recovery has not been validated.
Ordinary refresh/readback still performs one broad read.

Each broad reply is applied as a configuration snapshot. The short replies
are captured by the existing safe payload path but are not applied as complete
snapshots: Mini returns empty 0x1001/0x1004 tables, while the observed Power 2000
0x1001 contains a nested 0x100F accessory record. Their receipt must not erase
basic configuration or relax unknown-table write safety. No accessory controls
or new interpretation of these tables is introduced.

The observed request restores reads of 0x101C, 0x101D, and 0x1021 that the
historical literal omitted. This does not restore previously removed auxiliary
controls or assign meanings to those fields; they remain unexposed.

The device does not necessarily return every requested key. Returned-key presence is itself useful model/feature evidence; see `model-differences.md`.

Known parsed records include:

- `0x1000`: base information including firmware strings;
- `0x1005`: charge/discharge limits;
- `0x1006`: retained for safe write preservation where present;
- `0x100D`: nested output-interface state table (`0x1014` records);
- `0x100E`: known identifier/command companion record; redact in diagnostics;
- `0x1015`: device timezone offset in minutes;
- `0x1017`: tariff time-slot record;
- `0x1018`: Power 2000 scheduled-energy/off-peak/peak settings;
- `0x101E`: Power 1000 Mini charging-mode table (`0x101F` records).

A 0x60 read increments the config-read counter and updates the device-reported configuration snapshot/cache.

## 0x61 realtime telemetry

`0x61` is parsed throughout setup and retained internally. HA publication through the telemetry throttle starts only after initialization completes.

See `telemetry.md`.

## 0x62 configuration report

**Observed correction from the October 12 capture:** Mini can emit 0x61 first,
then the app completes six 0x60 GETs before the first 0x62 arrives. On another
connection the same Mini emits 0x62 first. A later 155.5-second report gap
coexists with continuing telemetry. Therefore neither initial report arrival
before GET nor a ten-second report cadence is guaranteed. The former strict
HA startup gate has therefore been removed.
See [timings and evidence](../implementation/app-startup-order-2026-10-12-capture.md).

`0x62` is parsed using the same configuration parser as `0x60`. It is the preferred passive source for confirming recent writes.

**Observed (Power 2000 with one expansion battery, 2026-09-26):** the latest
0x62 contains a `0x1001` table with one `0x100F` record absent from the latest
0x60 reply in that diagnostic. Accessory battery fields are **Inferred** from
this record; see [layout and limitations](packet-format.md#power-2000-accessory-table-0x1001--0x100f).
They are not currently exposed by the configuration parser. This difference
does not establish command-exclusive availability or a writable table.

When an unsolicited frame has:

```text
sender   = 0xAB
receiver = 0x02
cmd_type = 0x40
cmd_id   = 0x62
```

the integration schedules a best-effort ACK using the same sequence and:

```text
cmd_type = 0x80
payload  = 01
```

0x62 ACKs remain best-effort during initialization and normal operation;
failures are logged at debug level. Reports are not an initialization barrier.

**Observed in the October 9 Android capture:** all 22 reports across the three
successful app sessions receive this same ACK (Mini two, Power 2000 twenty).
The first report is received and ACKed before the first GET in every session.
This supports retaining ACKs; it does not prove the app explicitly waits for
the first report. The later October 12 capture disproves a universal
report-before-GET prerequisite.

## 0x63 writes

`0x63` is a request/response setting transaction. A matching-sequence response with command type `0x80` proves request completion. The payload contains per-property result codes.

**Observed app-only initialization difference:** both Power 2000 sessions in
the October 9 capture also send a 0x63 containing identifier companion 0x100E
and one-byte 0x1023 after the broad reads. Mini does not. The latter property's
meaning is **Unknown**; this is not evidence of a reconnect/reset command or
authorization to add the write to HA initialization.

Currently decoded write-result IDs include:

```text
0x1005 0x1006 0x100D 0x100E 0x1016 0x1018 0x101E 0x1023
```

Result code zero is treated as success for the expected property.

A successful 0x63 ACK does **not** by itself prove the device's later state. The manager records an optimistic local update and separately verifies it using a later device report. See ADR `0003-read-modify-write-and-verification.md`.

Verification attempts are revisioned per property. If a newer write supersedes
an older pending verification, the old attempt ends as
`superseded_by_new_write`; a delayed report for the old revision must not
override the newer target.

### Read-modify-write rules

- `0x1005`: charge/discharge limits. Preserve current `0x1006` where present and include the command companion record.
- `0x100D`: rewrite the complete known nested output table. Refuse the write if unknown/malformed nested data is present.
- `0x1016`: complete tariff-table replacement. Writes wrap each output record
  as a nested `0x0016` TLV; reads report the corresponding records as `0x1017`.
  **Confirmed on Power 2000:** the all-day peak/off-peak preset write envelope
  and complete 24-hour coverage require two same-kind everyday records:
  `00:00-23:59` and `23:59-00:00`. The first record alone does not include the
  23:59 minute.
  **Inferred for detailed schedules:** writable kind, day mode, weekday mask,
  reserved bytes, and minute fields use the same ten-byte positions seen in
  `0x1017` reads and in confirmed all-day `0x0016` writes. The
  `set_tariff_schedule` action uses this mapping, restricts reserved bytes to
  zero, rejects overlapping periods, and replaces the whole table. Detailed
  weekday/time writes have byte-level tests but have not been validated on real
  hardware in the agent environment. The 64-period software limit is derived
  from DUM frame capacity, not a confirmed DJI Home/device record limit.
- `0x1018`: Power 2000 scheduled energy settings. Modify only confirmed offsets; do not overwrite diagnostic-only candidate fields.
- `0x101E`: rewrite the complete known charging-mode table. Refuse the write if unknown/malformed nested data is present.

### 0x1018 field ownership

The Power 2000 0x1018 value is 86 bytes (`0x56`). Writers first obtain the
current value and edit only the confirmed fields below:

| Offset | Current treatment |
|---:|---|
| `0x00` | unknown leading value; preserve |
| `0x01` | energy optimization mode; edit only when requested |
| `0x02` | peak discharging; edit only when requested |
| `0x03` | off-peak charging; edit only when requested |
| `0x04–0x07` | off-peak charging-power maximum; use for validation and preserve |
| `0x08–0x0B` | off-peak charging-power minimum; use for validation and preserve |
| `0x0C–0x0F` | confirmed off-peak charging-power setting; edit only when requested |
| `0x10–0x55` | flags, candidate power values, reserved/unparsed data; preserve |

The combined `dji_power_bt.set_scheduled_energy_settings` service can update the
four confirmed settings in one read-modify-write transaction. Unspecified
fields retain their current bytes, and a request whose values all already match
does not send a 0x63 write. The 0x1016/0x1017 tariff table is separate and is not
part of this transaction.

Do not treat the watt-looking integer near offset 30 or the candidate value at
offset 34 as the active setting. Power 2000's 10 W input step comes from the
verified model profile, not automatic interpretation of offset 34.

## 0x66 HMS/auxiliary notification

The parser recognizes a provisional HMS record shape and tracks timestamp-independent body transitions. It is high-frequency traffic and does not publish every frame directly to all Home Assistant entities.

If the timestamp-independent body matches the previous body, the manager reuses the previous structural parse and only refreshes frame-specific fields. This fast path must preserve transition detection and diagnostic counters.

See `telemetry.md` and `unknowns.md`.

## 0x6A authentication

Sensitive. Excluded from payload capture.

Two-step session/authentication sequence is documented in `authentication.md`.

## Safe payload capture command set

The integration may retain payloads only for:

```text
0x60 0x61 0x62 0x63 0x66
```

Do not add `0x6A` to this safe set.
