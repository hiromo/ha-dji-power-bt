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

The manager sends the retained 48-byte `DEFAULT_STATUS_REQUEST_PAYLOAD` literal.
Historically its two-byte source-code groups have been described as requesting
these keys:

```text
0x1002 0x1003 0x1005 0x1006 0x1007 0x1008
0x1009 0x100A 0x100B 0x100C 0x100D 0x100E
0x1015 0x1016 0x1018 0x1019 0x101B 0x101E
0x1020 0x1022 0x1023 0x1024 0x1025
```

**Unknown request grammar:** those source-code groups do not independently
establish the device's field boundaries or endianness. Another implementation
sends the three-byte GETs `00 01 10` and `00 04 10` instead. Under the unconfirmed
interpretation `00 + little-endian 16-bit selectors`, our literal would leave a
trailing `25` byte. Successful configuration replies prove the literal has been
accepted, not that every named key was requested as intended. See the
[GET comparison backlog](unknowns.md#configuration-get-grammar-and-recovery)
before changing this traffic. Do not silently append a byte or replace it with
module sweeps on the strength of this interpretation alone.

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

`0x61` is parsed as realtime metrics. It updates battery/power state and schedules Home Assistant publication through the telemetry throttle.

See `telemetry.md`.

## 0x62 configuration report

`0x62` is parsed using the same configuration parser as `0x60`. It is the preferred passive source for confirming recent writes.

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

Do not make a 0x62 ACK failure fatal to the whole integration; current behavior logs it at debug level.

## 0x63 writes

`0x63` is a request/response setting transaction. A matching-sequence response with command type `0x80` proves request completion. The payload contains per-property result codes.

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
