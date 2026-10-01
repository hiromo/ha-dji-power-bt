# HMS error codes and charging-state observations

This is an appendable catalog of observed codes, not a production decoding
table. Evidence labels follow [README.md](README.md#evidence-labels).
An HMS `alarm_id` does not by itself establish severity or even a fault;
`report_level = 0` has no confirmed severity meaning.

## HMS code catalog (command 0x66)

IDs below are hexadecimal, including DJI Home's displayed `28000023`.
The wire field is a little-endian u32. Keep telemetry status bytes in the
separate table below; they are not HMS IDs.

| HMS ID | Wire ID bytes (u32le) | Observed model | Sensor / level / reserved | Meaning and confidence | Evidence / limitations |
|---|---|---|---|---|---|
| `0x28000023` | `23 00 00 28` | Power 2000 | `3 / 0 / 0` | **Observed:** DJI Home identifies an SDC-connected accessory software-version error | [App-matched observation](telemetry.md#observed-hms-code-0x28000023). Also retained in the September 26 history below; exact incompatible versions and clearance cause remain unknown. |
| `0x28000037` | `37 00 00 28` | Power 1000 Mini | `3 / 0 / 0` | **Unknown:** intermittent alarm during a high-load appliance run | [Comparison](telemetry.md#observed-hms-code-0x28000037): absent during a later approximately 981 W / 48.0 C run; not established as a simple high-temperature or high-load warning. |
| `0x28000038` | `38 00 00 28` | Power 2000 | `3 / 0 / 0` | **Hypothesis:** one ultralow-SoC / low-cell-voltage recovery phase | [Recovery history](unknowns.md#power-2000-hms-alarm-0x28000038): 324 reports on firmware `01.00.1500`; cleared before protective charging and Energy Saver unavailability ended. Not a demonstrated maintenance-charge code. |

For a new code, append a row with exact ID bytes, model/firmware scope,
sensor/level/reserved values, evidence label, app wording if actually observed,
and a link to a dated observation. Keep additional occurrences of a known code
in its evidence section. Do not fill unknown meanings from neighboring IDs or
assume a meaning carries across models. Upgrade a meaning to **Confirmed** only
with repeated device evidence; parser success confirms structure, not meaning.

## Charging-state candidates (command 0x61, not HMS codes)

Offsets are zero-based within the TLV value, excluding the four-byte TLV
header. These observations are limited to Power 2000 firmware `01.00.1500`.

| Field / value | Observed context | Interpretation status | Evidence |
|---|---|---|---|
| `0x3050[6] = 0x00` | 10% SoC; AC input stopped; peak-period discharge; banner cleared | **Observed** correlation; generic state meaning **Unknown** | [Earlier paired capture](unknowns.md#power-2000-0x30204-and-0x30506) |
| `0x3050[6] = 0x02` | 5% SoC; protective AC charging; Energy Saver unavailable | **Observed** correlation; ordinary AC charging vs protective recovery remains **Unknown** | Same paired capture |
| `0x3050[6] = 0x05` | 70% SoC; operator identifies maintenance charging; DJI Home says this charge will reach 100% | **Observed** value; **Hypothesis:** maintenance-charge state/reason, potentially a compound value rather than an enum | September 26 observation below |

Append status candidates by command, record ID, offset, and raw value. Do not
assign a fabricated `0x280000xx` ID to a telemetry status. In particular,
`0x05` is neither HMS ID `0x28000005` nor an established error code.

## 2026-09-26 maintenance-charge observation

### Source and scope

The operator supplied a Home Assistant diagnostic export (download copy
suffix `(2).json`) and `Screenshot_20260926-143853.png`, explicitly identifying
the diagnostic as captured during maintenance charging. The JSON's last
0x61/0x66 reports are at **2026-09-26 14:40:04 +09:00**. The screenshot filename
indicates 14:38:53 (the visible phone clock reads 2:38); these are nearby
observations, not synchronized frames.

Device: DJI Power 2000 (`0x94`), station firmware `01.00.1500`, communication
firmware `03.03.0000`. This analysis rechecks supplied evidence offline; it is
not a new real-device experiment. No identifying export filename, device
identifiers, authentication data, or complete diagnostic dump is stored here.

**Observed app display:**

- `バッテリーのメンテナンス中です。今回は100%まで充電します`
- `メンテナンス充電`, with Energy Saver shown unavailable during maintenance.
- 70% SoC, 33.1 C, 1 h 3 min remaining, total and AC input both 1,497 W.

**Observed latest diagnostic:** 70% aggregate SoC, 33.1 C, 70 minutes
remaining, AC/total input 1,500 W, AC/total output 329 W. The station-only SoC
candidate is 86%; it must not be substituted for aggregate SoC. The timing
difference prevents requiring exact power/time agreement with the screenshot.

### 0x66 does not contain a new maintenance code in this export

The latest command-set `0x5A`, command `0x66`, type `0x00`, sequence 20115
has a 20-byte payload: the existing 16-byte keyed header followed by:

```text
00 00 00 00
----- -----
meta  count = 0
```

The length exactly matches `4 + 0 * 8` after removing the keyed header. This
is an empty report, not an unrecognized packet or an unparsed hidden record.
Reparsing each retained body with the existing HMS parser agrees with the
exported parse results.

All retained timestamp-independent history entries (times are +09:00):

| First seen | Last seen | Reports | Body / interpretation |
|---|---|---:|---|
| 2026-09-24 01:08:35 | 2026-09-26 12:08:55 | 207,564 | `00 00 00 00`; empty |
| 2026-09-26 12:22:50 | 2026-09-26 14:33:26 | 7,617 | `00 00 01 00 23 00 00 28 03 00 00 00`; only `0x28000023`, sensor 3, level 0, reserved 0 |
| 2026-09-26 14:39:05 | 2026-09-26 14:40:04 | 58 | `00 00 00 00`; empty |

Counts total 215,239, matching 3 full parses plus 215,236 fast-path hits.
The history limit is 20 and only three entries are retained. It groups repeated
bodies and does not establish uninterrupted reception between first/last times.
There are observation gaps, notably **14:33:26 to 14:39:05**, spanning the
screenshot. The exact clearing time/cause of `0x28000023` is therefore unknown;
this export alone does not prove a successful accessory firmware update.
The separate payload capture was inactive and contains zero frames.

**Observed conclusion:** the only nonempty HMS ID retained is `0x28000023`.
Neither a second maintenance-related ID nor `0x28000038` is present. The data
does not support the proposed additional code in the same 0x66 report. It also
cannot rule out a transient code at maintenance start or during a reception gap.

### A different candidate is present in 0x61

The latest 0x61 payload (sequence 20114) contains these TLVs, independently
checked against the diagnostic metric fields:

```text
20 30 0c 00  58 1b 46 00 01 98 21 00 00 ee 0c 01
50 30 07 00  02 01 02 02 00 00 05
```

`0x3020[4] = 0x01` is the same battery status as the earlier protective-charge
sample. The seven-byte `0x3050` differs from that sample only at offset 6:
`02` then, **`05` now**. This makes `0x3050[6]` a useful maintenance-state
candidate, while the unchanged `0x3020[4]` does not distinguish those two
charging contexts.

The current `0x3010` is 38 bytes and contains identifier-like ASCII; it is not
the all-zero record seen in the earlier recovery captures. Its identifying
contents are deliberately omitted. Consequently, this is not a controlled
comparison in which only `0x3050[6]` changed, and that record cannot yet be
ruled out as additional state/context.

**Hypothesis:** `0x3050[6] = 0x05` participates in the app's maintenance-charge
state. **Unknown:** whether it is an enum, flags, a charge reason, an accessory
condition, or a compound state; whether it remains present for the entire
maintenance interval; and whether DJI Home directly uses it for the banner.
One contemporaneous app/diagnostic pair does not establish those semantics.

### Next discriminating evidence

1. Retain synchronized 0x61 status bytes, 0x66 transitions, SoC, power, and app
   state immediately before, during, and after a maintenance cycle. Establish
   whether `05` follows the banner while charging continues on both sides.
2. Compare ordinary AC charging without maintenance on the same firmware and
   accessory configuration; then repeat maintenance to test reproducibility.
3. Compare ultralow-SoC recovery (`02` observed previously) separately from
   full-charge maintenance. Do not conflate the shared Energy Saver restriction.
4. Inspect all simultaneous HMS records and gaps; absence in this export is
   narrower evidence than absence from the protocol. Sanitize identifier-bearing
   records before retaining additional examples.

These candidates remain diagnostic-only and do not authorize new controls,
automatic error labels, or a change to entity availability.
