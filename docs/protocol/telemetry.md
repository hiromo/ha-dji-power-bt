# Telemetry and HMS

## 0x61 realtime telemetry

`0x61` carries the realtime metrics used for Home Assistant sensors and diagnostics.

### Battery record 0x3020

**Confirmed current offsets used by the integration**

```text
offset  size  interpretation
0       2     SoC * 100 -> percent
2       2     remaining time in minutes
4       1     battery status code; semantic meaning not fully decoded
5       4     legacy duplicate SoC candidate * 100; station SoC inferred below
9       2     battery temperature * 100 -> degrees C; station temperature observed below
11      1     exported as battery unit count; count scope unresolved
```

Raw `0x3010`, `0x3020`, and `0x3050` values are retained in diagnostics for high-temperature/charging-inhibit investigation. Do not expose a `charging_allowed` or `inhibit_reason` semantic until the code is confirmed.

The exported field names are `raw_0x3010_hex`, `raw_0x3020_hex`, and
`raw_0x3050_hex`. They are also attributes of the disabled-by-default battery
status diagnostic sensor.

### Power 2000 with one Power Expansion Battery 2000

- **Observed:** with one expansion battery connected via SDC, HA SoC reports
  the combined percentage, while battery temperature reports the station's
  temperature (`0x3020[0:2]` and `[9:11]`, respectively).
- **Inferred:** `0x3020[5:9]`, currently named
  `soc_duplicate_percent_candidate`, is station-only SoC, not a duplicate.
- **Observed:** `0x62` contains an accessory table `0x1001 -> 0x100F`.
  Accessory serial-number and firmware fields match the app's labels;
  SoC, capacity, and temperature interpretations remain **Inferred**.
  See the [field layout](packet-format.md#power-2000-accessory-table-0x1001--0x100f).
- **Unknown:** aggregate-SoC calculation and `battery_unit_count` scope.
  A value of 1 with two physical batteries does not establish a total count.
  Missing SDC power records do not establish accessory disconnection or zero
  energy transfer.

These conclusions cover one hardware/firmware combination with accessory
software-version error `28000023`; normal post-update behavior, multiple
accessories, and other station models remain unverified.

### Power 2000 status-field correlations

**Observed; semantics unresolved**

A paired Power 2000 firmware `01.00.1500` capture compared a low-SoC
protective AC-charge snapshot with the later return to peak-period battery
discharge:

| State | SoC | `battery_status_code` (`0x3020[4]`) | `0x3050[6]` |
|---|---:|---:|---:|
| protective AC charge; DJI Home showed Energy Saver unavailable | 5% | `1` | `0x02` |
| AC input stopped; peak-period battery discharge resumed | 10% | `2` | `0x00` |

Byte indexes are zero-based. `0x3010` remained all zero in both snapshots.
These transitions are correlated with charging versus discharging as well as
with the app banner transition, so they do not establish a dedicated Energy
Saver-unavailable flag. In particular, do not yet map status code `1` to
charging, status code `2` to discharging, or `0x3050[6] == 0x02` to protected
charging. See `unknowns.md` for the competing interpretations and experiments.

## Power record 0x3030

The first four bytes provide total output and input power as 16-bit little-endian watts.

Nested power telemetry uses a hierarchy of `0x3031` -> `0x3032` -> `0x3033` -> `0x3034` records.

Current group type names:

| Raw | Group |
|---:|---|
| 1 | `ac_inlet` |
| 2 | `ac_outlet` |
| 3 | `usb` |
| 4 | `sdc` |
| 5 | `12v` |
| 6 | `xt60` |

Current interface type names:

| Raw | Interface |
|---:|---|
| 1 | `ac_inlet` |
| 2 | `ac_outlet` |
| 3 | `usb_a` |
| 4 | `usb_c` |
| 5 | `sdc` |
| 6 | `sdc_lite` |
| 7 | `12v` |
| 8 | `xt60` |

### AC direction semantics

Use device-port direction, not site topology:

```text
ac_inlet_input_power_w   power entering the DJI Power device via AC inlet
ac_inlet_output_power_w  opposite direction; retained diagnostically, meaning not fully confirmed
ac_outlet_input_power_w  opposite direction; retained diagnostically, meaning not fully confirmed
ac_outlet_output_power_w power leaving the DJI Power device via AC outlet bank
```

Do not rename these to `grid_*`; the upstream AC source could be utility power, a generator, another inverter, or another power station.

**Confirmed Power 2000 mapping evidence:** with simultaneous AC and SDC solar
input, DJI Home showed total input 1,515 W, AC 1,478 W, and SDC 37 W. The same
0x3030 report contained:

```text
total input                                      1515 W
group_type=1 / interface_type=1 / input_w        1478 W
group_type=4 / interface_type=5 / input_w          37 W
```

This is the direct device/app comparison supporting
`group_type=1 / interface_type=1 / input_w` as Power 2000 AC-inlet input.
The opposite two AC directions remain unconfirmed.

Diagnostics also retain the objective total-power delta
`input_minus_output_w = input_power_w - output_power_w`. Do not turn this delta
back into an inferred operating-state label.

### Missing vs zero per-port data

A missing individual port record remains `None`/unknown. A reported record with zero power is `0 W`. This distinction is intentional.

Group/interface aggregate values can be zero when a valid packet contains no matching record.

## USB, SDC, 12 V, and XT60

USB-A and USB-C share a protocol group; the normal Home Assistant aggregate sensors are USB input/output totals, while per-port sensors are disabled by default.

SDC input/output is exposed when supported. SDC may carry external MPPT/accessory traffic.

XT60 input/output parsing is intentionally retained for interface type `8` and group type `6`. Do not remove it merely because one current capture lacks such records.

## 0x66 HMS/auxiliary reports

The [HMS code catalog](hms-codes.md) collects known IDs in an appendable table
with evidence labels and links. Its separate telemetry-status table must not
be interpreted as additional HMS IDs.

**Observed (2026-09-26):** a Power 2000 maintenance-charge diagnostic has an
empty latest 0x66 body and only `0x28000023` in its nonempty retained history.
The latest 0x61 `0x3050` is `02 01 02 02 00 00 05`, with battery status
`0x3020[4] = 1`. **Hypothesis:** `0x3050[6] = 0x05` relates to maintenance
charging; it is not a newly observed HMS error code. See the
[dated evidence and reception gaps](hms-codes.md#2026-09-26-maintenance-charge-observation).

The structural parser is provisional. It records alarm ID, sensor index, report level, and reserved bytes when the body matches the known record shape.

An empty body is `00 00 00 00`.

### Fast path

0x66 can arrive roughly once per second for long periods. The manager compares the timestamp-independent body bytes with the previous body. When unchanged it reuses the previous parsed record and increments `fast_path_hit_count`; a changed body triggers a full parse and increments `full_parse_count`.

Do not optimize away body-transition detection or timestamp updates.

### Observed HMS code 0x28000023

**Observed:** DJI Home code `28000023` means a software-version error of an
accessory connected to the SDC port. It corresponds to hexadecimal HMS ID
`0x28000023` (`23 00 00 28` as u32le), not decimal 28000023.
The observed record has sensor index 3, report level 0, and reserved value 0.

Exact incompatible versions, sensor-index meaning, severity, and clearance
following a firmware update remain **Unknown**.

### Observed HMS code 0x28000037

**Observed, semantic meaning unresolved**

Power 1000 Mini has emitted:

```text
alarm_id     = 0x28000037
sensor_index = 3
report_level = 0
reserved     = 0
```

It was observed intermittently during one prolonged high-load appliance run. However, a later capture at approximately 981 W battery discharge and 48.0 C battery temperature, with DJI Home showing the temperature in red, produced only empty 0x66 bodies for the entire runtime window.

Therefore do **not** map `0x28000037` to a simple "high battery temperature" or "near-1000 W load" warning. It may depend on a different internal temperature sensor, duration, operating mode, charge/bypass state, SoC, or another condition.

Keep it diagnostic-only until controlled comparisons identify the trigger and operational consequence.

### Observed HMS code 0x28000038

**Observed on Power 2000; semantic meaning unresolved**

During one all-day-peak Scheduled-mode low-SoC recovery cycle on firmware
`01.00.1500`, alarm `0x28000038`, sensor index 3, report level 0, reserved 0,
was reported 324 times from 03:07:16 through 03:12:42. The 0x66 body was empty
before and after that interval.

DJI Home showed 5% SoC and active AC charging at 03:12:45, three seconds after
the alarm cleared. The app's Energy Saver-unavailable banner and protective
charging continued beyond the HMS transition; at 10% the banner cleared, AC
input stopped, and peak-period battery discharge resumed without another 0x66
body change. Therefore `0x28000038` is not currently interpreted as the banner
state or as the complete protective-charge interval.

The leading hypothesis is that it marks one ultralow-SoC or low-cell-voltage
recovery phase below the normal forced-bypass threshold. The SoC at first alarm
was not retained in the diagnostic snapshot; field recollection places it near
3%. See `unknowns.md` for the evidence classification and reproduction plan.

## Publication throttle

Realtime packets are always received and parsed. Home Assistant listener publication is throttled to the configured telemetry interval, default 5 seconds and allowed range 1-60 seconds. This limits HA state-update load without reducing protocol observation rate.
