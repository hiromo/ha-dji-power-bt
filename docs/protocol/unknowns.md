# Protocol unknowns and investigation backlog

This file records unresolved observations so future agents do not convert guesses into implementation facts.

## DUM transport version vs application/product revision

### DUM frame version

**Confirmed structural field; observed value 1**

`DumlFrame.version = raw[2] >> 2` is the 6-bit version portion of the packed DUM frame length/version word. The current builder emits version 1.

The integration currently does not aggregate this value in diagnostics. A useful future diagnostic would record the set/count of transport versions seen.

### 0x1000 bytes 4..6

**Observed; hypothesis: product/platform revision tuple**

Current examples:

```text
Power 2000      13 01 01
Power 1000 Mini 10 01 01
```

**Observed additional sample (2026-09-26):** Power 2000 with one expansion
battery reports `13 01 02`, still on station firmware `01.00.1500`.
This weakens an exclusively model-static interpretation of the whole tuple.
**Hypothesis:** byte 6 may reflect attached modules or configuration; a
same-station detach/reattach comparison is needed before calling it a count.

These bytes differ by model while the last two bytes currently match. They may describe a product/platform family, hardware revision, application schema generation, or related metadata.

Do not call them a protocol version yet.

Best experiment: compare the same physical model before and after firmware updates, and compare additional units/models. If bytes 4..6 remain model-stable while firmware strings change, product/platform identity becomes more likely. If they change with protocol-affecting firmware, schema/revision becomes more likely.

### 0x1000 other candidates

Observed Power 2000 and Power 1000 Mini values contain additional fields around:

- bytes 0..3: printable two-character-looking value plus NULs; possible region/product channel/variant;
- bytes 40..43: model-dependent integer-like value; appears more like a rating/capacity than a version;
- bytes 44..46: model-dependent unknown;
- bytes 47..50: currently common integer-like value in compared units;
- byte 52: Power 2000/Mini difference; possible feature/family flag.

Keep these raw/diagnostic until multi-model evidence exists.

## 0x100C trailing byte

**Observed model difference**

Current examples have differed at the trailing byte:

```text
Power 2000      ... 00
Power 1000 Mini ... 01
```

This looks flag-like but the parent record meaning is unresolved. Do not use it as a capability gate yet.

## Returned configuration-key set

### Configuration GET grammar and recovery

**Observed in source and synthetic wire execution, not a new device capture:**
our retained GET literal is 48 bytes, beginning `00 00 10 02 10 03` and ending
`10 23 10 24 10 25`. The zuyan9 implementation at commit
`4682acbef33bfb9b4734818cc640f59dbd7c2758` instead sends two GET payloads,
`00 01 10` and `00 04 10`, called module sweeps there.

**Hypothesis:** a one-byte operation prefix followed by little-endian 16-bit
selectors would interpret the other requests as `0x1001` and `0x1004`. Applying
that grammar to our literal gives 23 complete selectors plus an unmatched
trailing byte `25`. The current two-byte source-code grouping is not evidence
against that interpretation, but neither implementation documents a complete
device-validated GET grammar. Do not treat this as a confirmed malformed packet
or infer the necessary repair byte.

**Unknown:** whether selector type, missing terminator, requested records, or
GET mode affects the station's session/reporting state; whether any difference
explains recovery after DJI Home. The September diagnostics repeatedly fail
after authentication during the initial GET, making this a useful controlled
comparison. Compare DJI Home GETs and replies on the same firmware, then test
one request mode at a time without changing ACK policy or connection parameters.
Preserve unknown returned records and existing write safety checks.

The other implementation also omits our conditional `0x62/0x40` ACK. Whether
DJI Home sends `0x62/0x80` with payload `01`, and whether continuous ACK handling
affects long-session station behavior, remain separate capture questions.
See the [comparison and change review](../implementation/ble-comparison-and-review-2026-09-11.md).

### Returned records

**Observed and strongly informative**

Power 2000 and Power 1000 Mini return different subsets of requested 0x60 keys. This may be a better long-term capability-discovery mechanism than static model tables, but safe semantics for every key are not yet known.

Future work should record `keys_seen` in diagnostics without changing write behavior, then compare across firmware and models.

## Unresolved Mini keys

Current Power 1000 Mini captures may include `0x101B`, `0x1022`, and `0x1023`. Their meanings are unresolved. Preserve payloads diagnostically where safe and do not expose user controls without targeted captures.

## Power 1000 Mini SDC control direction

The Power 1000 Mini 0x100D SDC1 record changes with DJI Home's `SDC` control,
so it is a confirmed controllable interface record. It is not yet confirmed
whether disabling that record also stops SDC input. Do not narrow the protocol
meaning to an output-only switch without a controlled input-side capture.

## Unresolved Power 2000 key 0x1019

Present in current Power 2000 config responses, absent in current Mini responses. Meaning unresolved.

## Detailed 0x1016 tariff-table write limits

The all-day two-record `0x1016` write shape is capture-confirmed. Detailed
weekday and time fields are readable as ten-byte `0x1017` records, and their
positions align with the confirmed nested `0x0016` all-day write records. Using
those same positions for arbitrary detailed writes is currently **Inferred**.

The following remain unconfirmed across Power 2000 firmware versions:

- the maximum record count accepted by the station and DJI Home;
- whether the station reorders or coalesces equivalent records;
- whether gaps are accepted consistently;
- whether any valid DJI Home schedule uses nonzero reserved bytes;
- whether same-kind overlaps are accepted or normalized.

The integration rejects all overlaps, equal start/end times, nonzero reserved
bytes, and sub-minute input. It limits writes to 64 records so the DUM frame
remains within its transport length, but this is not evidence that the device
accepts 64 records. Capture DJI Home writes for mixed rates, weekday masks,
overnight periods, and the app's maximum record count before promoting the
detailed writer to Confirmed.

## 0x1018 candidate power fields

Power 2000 `0x1018` includes several watt-looking integers outside the confirmed off-peak power field. Current diagnostics name them only as candidates, including a value around offset 30, a possible step/granularity at offset 34, and tail values.

The writer must continue changing only confirmed fields. Do not use the candidate at offset 30 as the active off-peak charging power.

## Battery status and high-temperature charging inhibit

`battery_status_code`, raw `0x3010`, `0x3020`, and `0x3050` are retained because a Power 1000 Mini can stop charging at high temperature while continuing bypass/output behavior.

The exact charging-inhibit code/field is not yet confirmed. Do not expose a semantic `charging_allowed` or `inhibit_reason` entity until paired captures show the transition.

### Power 2000 `0x3020[4]` and `0x3050[6]`

**Observed correlation; meaning unresolved**

Two Power 2000 firmware `01.00.1500` snapshots from the same ultralow-SoC
recovery cycle differed as follows:

| Snapshot | SoC | Power flow | DJI Home state | `0x3020[4]` | raw `0x3050` |
|---|---:|---|---|---:|---|
| 03:12:58 | 5% | 1,397 W input / 239 W output | Energy Saver unavailable; protective AC charge | `01` | `02 01 02 02 00 00 02` |
| 03:19:05 | 10% | 0 W input / 335 W output | banner cleared; peak-period discharge | `02` | `02 01 02 02 00 00 00` |

Only `0x3020`, power record `0x3030`, and `0x3050` changed among the top-level
0x61 records. `0x3010` remained all zero. The two available states change three
conditions together: app-banner visibility, AC/protective charging, and power
direction. They therefore cannot distinguish these candidate interpretations:

- `0x3020[4]`: generic battery operating status, possibly charging versus
  discharging;
- `0x3050[6] == 0x02`: generic AC-charge state;
- `0x3050[6] == 0x02`: protective-charge or low-SoC-recovery state;
- one or both fields participate, together with SoC/mode, in DJI Home's
  Energy Saver-unavailable display logic.

Current field experience reports that Energy Saver unavailable, AC charging,
and protective charging have occurred together, not independently. The banner
has so far been observed during periodic full-charge maintenance (about once
per five full charges) and during ultralow-SoC forced recovery to
`discharge limit + 10%`. This is reported experience, not proof that no other
case exists.

Recommended discriminating captures:

1. ordinary off-peak or manually initiated AC charging without the banner;
2. periodic full-charge maintenance with the banner (one sample now recorded
   below; synchronized start/end transitions are still needed);
3. ultralow-SoC recovery below and above `discharge limit + 5%`;
4. one-second 0x61 snapshots immediately before and after the banner clears,
   ideally while holding power direction constant;
5. bypass operation below the forced-bypass threshold before active protective
   charging begins.

Do not expose these bytes as a charging, protective-charge, or Energy Saver
entity until at least one such comparison separates the currently coupled
states.

### Maintenance-charge candidate `0x3050[6] = 0x05`

**Observed (2026-09-26):** the operator-provided Power 2000 maintenance-charge
diagnostic reports `0x3050 = 02 01 02 02 00 00 05`, `0x3020[4] = 1`, 70% SoC,
and 1,500 W AC input. Nearby DJI Home imagery explicitly says maintenance
charging to 100%. The latest 0x66 is empty; its retained history contains only
one nonempty ID, `0x28000023`, before a reception gap. No new maintenance HMS
ID was found. See the [analysis and appendable code catalog](hms-codes.md).

**Hypothesis:** offset 6 value `05` represents a maintenance-charge state or
reason, distinct from the earlier low-SoC protective-charge value `02`.
The enum/bitfield interpretation, accessory influence, and transition timing
remain **Unknown**. The current `0x3010` also differs from the earlier all-zero
sample and contains identifier-like data, so the comparison is not controlled.
Capture ordinary charging and maintenance start/end on the same configuration
before assigning a semantic label or using this byte for availability/control.

## Power 2000 station and expansion-battery fields

The [single-accessory conclusions](telemetry.md#power-2000-with-one-power-expansion-battery-2000)
distinguish combined SoC from the **Inferred** station-only
`soc_duplicate_percent_candidate`. Accessory SN and firmware app-label
correspondence is **Observed**; see the
[0x100F layout](packet-format.md#power-2000-accessory-table-0x1001--0x100f).
Cross-device field widths, capacity scaling, and behavior across updates
still need comparative evidence.

Remaining **Unknowns** and discriminating experiments:

- Compare synchronized app readings and 0x61/0x62 fields while the two SoCs
  diverge/change to verify station/accessory mappings and scaling. Retain only
  non-identifying protocol conclusions in the repository.
- Compare the same station with zero/one/multiple expansion batteries to
  establish `0x3020[11]` count scope, `0x1000[6]`, 0x100F leading-byte meaning,
  record repetition, ordering, and stable identity. A value of 1 with one
  accessory does not alone prove an accessory count.
- Retain before/after-update values for the now app-matched accessory firmware
  `10.03.00.15`. Do not infer normal accessory power behavior
  from this software-version-error sample.
- Establish aggregate-SoC weighting/rounding and per-record update cadence;
  equal nominal capacity and nonsynchronous screenshots do not prove a formula.
- Determine whether accessory power appears in SDC records in other states;
  absence of a leaf must not be interpreted as accessory disconnection.

The existing diagnostic field names are retained for compatibility. These
observations do not authorize new controls or writes to the accessory table.

## HMS alarm 0x28000023: displayed meaning observed

DJI Home explicitly identifies `28000023` as an SDC-connected accessory
software-version error; the matching HMS ID is documented in
[telemetry.md](telemetry.md#observed-hms-code-0x28000023).
The displayed meaning is no longer unresolved. The exact version comparison,
affected accessory range, severity, and clearance after a firmware update
remain **Unknown**; a before/after-update capture is needed.

## HMS alarm 0x28000037

**Observed; meaning unresolved**

Power 1000 Mini emitted alarm `0x28000037`, sensor index 3, report level 0 during one high-load appliance run. The alarm appeared and disappeared in several intervals.

A later runtime at about 981 W battery discharge and 48.0 C battery temperature, with the DJI app temperature indicator red, produced no HMS alarm and only empty 0x66 bodies.

This rules against a simple mapping such as "battery temperature is high" or "load is near 1000 W". Candidate triggers include another internal sensor, thermal duration, inverter temperature, charging/bypass state, SoC, or a compound condition.

Recommended experiment: correlate exact 0x66 transitions with input power, output power, SoC, battery temperature, AC-input presence, bypass/discharge state, and app-visible warnings during repeatable appliance cycles.

## Power 2000 HMS alarm 0x28000038

**Observed structure and timing; meaning unresolved**

A Power 2000 firmware `01.00.1500` diagnostic history recorded:

```text
alarm_id     = 0x28000038
sensor_index = 3
report_level = 0
reserved     = 0
first seen   = 2026-08-28 03:07:16 +09:00
last seen    = 2026-08-28 03:12:42 +09:00
occurrences  = 324
```

The timestamp-independent 0x66 body was empty through 03:07:15, contained this
single record for about 5 minutes 26 seconds, and was empty again from 03:12:43
through at least 03:19:05. The following paired observations constrain its
meaning:

- at 03:12:45, three seconds after the alarm cleared, DJI Home showed 5% SoC,
  active AC charging, and Energy Saver unavailable;
- at 03:12:58, diagnostics still showed 5% SoC, 1,397 W input, 239 W output,
  `battery_status_code = 1`, and `0x3050[6] = 0x02`;
- at 03:19:05, diagnostics showed 10% SoC, 0 W input, 335 W output,
  `battery_status_code = 2`, and `0x3050[6] = 0x00`; the app banner had cleared
  and peak-period battery discharge had resumed;
- no additional HMS pattern transition occurred during the 5%-to-10% charge or
  at the return to discharge;
- Home Assistant write history was empty, and shared 0x62 configuration values
  were byte-identical between the 03:11 and 03:16 reports.

**Reported field context**

The operator recalls SoC near 3% around the beginning of the alarm interval.
Power 2000 has also been observed to lose battery SoC slowly during extended
forced bypass at very low SoC. Neither the first-alarm SoC nor the instant that
AC protective charging began was retained alongside the HMS transition, so
these details are not capture-confirmed in this sequence.

**Leading inference**

`0x28000038` may identify an ultralow-SoC or low-cell-voltage recovery phase
between roughly 3% and the normal forced-bypass threshold of
`discharge limit + 5%`. It does not appear to identify the whole protective
charge or the whole Energy Saver-unavailable interval, because both continued
after the alarm cleared and until the reported SoC reached
`discharge limit + 10%`.

Competing hypotheses include a low-cell-voltage condition, a gentle/precharge
phase, a dwell timer before higher-power recovery, or another internal BMS
condition that happens to clear near reported 5% SoC.

Recommended experiment: reproduce the cycle while retaining synchronized
one-second SoC, input/output power, `0x3020`, `0x3050`, 0x66 transitions, and
DJI Home banner state. The key discriminator is whether AC input rises when the
alarm first appears, before it appears, or only when it clears. Repeat with a
nonzero discharge limit to test whether the alarm-clear and charge-release
thresholds shift to `limit + 5%` and `limit + 10%`.

## Report-level semantics

0x66 `report_level` values are parsed structurally but not semantically mapped. Do not equate level 0 with warning/information without comparative evidence.

## Uncertain reverse power directions

`ac_inlet_output_power_w` and `ac_outlet_input_power_w` are structurally decoded but their real-world semantics are not sufficiently confirmed for normal Home Assistant entities. Keep them diagnostic-only.

## How to close an unknown

When resolving an item:

1. preserve before/after raw captures;
2. identify a controlled physical state change;
3. reproduce on the same model at least twice when practical;
4. compare another model/firmware if claiming universality;
5. add parser/builder behavior tests;
6. move the confirmed meaning to the appropriate protocol document;
7. leave a short note here describing what evidence resolved it.
