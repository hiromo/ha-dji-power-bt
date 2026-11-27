# Model differences and capability signals

## Known discovery model codes

| Code | Model | Current support confidence |
|---:|---|---|
| `0x91` | DJI Power 1000 | discovery/basic conservative profile; model-specific tables not fully verified |
| `0x94` | DJI Power 2000 | primary verified model |
| `0x97` | DJI Power 1000 V2 | discovery/basic conservative profile; model-specific tables not fully verified |
| `0x98` | DJI Power 1000 Mini | primary verified model |
| `0x9E` | DJI Power Auro 2000 Elite | hardware-tested charging power, tariff presets and electricity prices |

Unknown model codes receive a conservative default capability set.

Real-hardware testing covers Power 2000, Power Auro 2000 Elite and Power 1000 Mini. Power 1000 and Power 1000 V2 keep conservative profiles until their
model-specific configuration and control tables receive equivalent validation.

## Static capability hints

Current static profiles are used to decide which Home Assistant entities may be created. These are conservative hints, not proof that every firmware exposes identical protocol tables.

### Power 2000 (`0x94`)

Current profile:

- Four USB-A ports, four USB-C ports and two SDC ports
- SDC supported
- 12 V accessory telemetry path retained
- XT60 accessory telemetry path retained
- tariff slots
- off-peak charging control
- off-peak charging power step 10 W
- peak discharging control
- charge/discharge limits
- AC output control
- energy optimization control

#### First single-expansion-battery observation (2026-09-26)

**Observed:** Power 2000 firmware `01.00.1500` / communication firmware
`03.03.0000`, with exactly one DJI Power Expansion Battery 2000 connected via
SDC. DJI Home shows station and accessory capacities of 2048 Wh each, with
separate SoC/temperature readings. HA's current SoC is combined, while its
battery temperature is the station's. See the
[telemetry conclusions](telemetry.md#power-2000-with-one-power-expansion-battery-2000).

**Inferred:** 0x3020 offset 5 carries station-only SoC; a nested 0x100F record
in 0x62's 0x1001 table carries accessory SoC/capacity/temperature/firmware.
No SDC power leaf was present in the latest telemetry despite the physical
connection. The exported `battery_unit_count` was 1 with two physical batteries,
so its scope remains unresolved. This first sample was obtained while DJI Home
reported accessory software-version error `28000023`; it does not establish
normal behavior after upgrading the accessory, behavior with multiple expansion
batteries, or equivalent layouts on other station models.

### Power Auro 2000 Elite (`0x9E`)

The static profile includes:

- Two USB-A ports, three USB-C ports and two SDC ports
- Charge and discharge limits and AC output control
- Energy optimization mode and tariff time slots
- Off-peak charging enable, off-peak charging power in 10 W steps, and peak discharging enable

Auro also reports a separate **Recharging Power** setting with device-reported
bounds and increment. It controls battery charging power. During bypass, an
active **Off-peak charging power** limit caps total AC input, including the
bypass load. See [Auro charging during bypass](#power-auro-2000-elite-charging-during-bypass).

Individual USB and SDC switches are disabled by default. SDC power telemetry
covers both ports together. See [Auro and Mini port controls](#auro-2000-elite-and-mini-port-controls)
and [Auro configuration writes](commands.md#auro-configuration-writes) for the
observed port records and verified tariff and price settings.

### Power 1000 Mini (`0x98`)

Current profile:

- Two USB-A ports, two USB-C ports and one SDC port
- USB-C input telemetry
- SDC supported and controllable
- 12 V accessory telemetry path retained
- XT60 accessory telemetry path retained
- charge/discharge limits
- AC output control
- charging-mode control

It does not use the Power 2000 tariff/off-peak/peak control model.

## Device-reported capability signals

**Observed startup variability (October 12):** the same Mini uses both
telemetry-first/GET-before-report and report-first ordering; Power 2000 retains
report-first ordering in the available samples. Broad and short GET bytes are
identical on Power 2000 and Mini in these samples. No fixed model-specific startup branch follows from
this evidence. See [ADR 0008](../decisions/0008-follow-observed-app-initialization.md).

**Observed and important for future capability discovery**

The integration requests a broad set of keys in 0x60, but devices return different subsets. The returned key set is a protocol-level feature signal.

Typical observed distinction:

| Key | Power 2000 | Power 1000 Mini | Interpretation |
|---|---:|---:|---|
| `0x1000` | yes | yes | common base info |
| `0x1005` | yes | yes | charge/discharge limits |
| `0x100D` | yes | yes | output-interface state table |
| `0x1015` | yes | yes | timezone |
| `0x1016` | yes | no in current captures | tariff table |
| `0x1018` | yes | no in current captures | scheduled-energy/off-peak/peak settings |
| `0x1019` | yes | no in current captures | unresolved Power 2000-side feature data |
| `0x101B` | no in current captures | yes | unresolved Mini-side feature data |
| `0x101E` | no in current captures | yes | charging-mode table |
| `0x1022` | no in current captures | yes | unresolved Mini-side feature data |
| `0x1023` | no in current captures | yes | unresolved Mini-side feature data/write-result candidate |

Do not immediately replace static capability gating with raw key presence. A returned key is strong evidence that a function/table exists, but safe write semantics still require a confirmed record structure.

### Power Auro 2000 Elite (`0x9E`) configuration reports

**Observed:** Auro configuration responses and periodic reports provide the
following model-specific evidence. This is a partial list of reported keys.

| Key | Evidence on Auro |
|---|---|
| `0x100D` | The output-interface table identifies individual USB-A, USB-C and SDC ports. |
| `0x1016` | Configuration responses and periodic reports contain 15-byte tariff rows with a per-period price field. |
| `0x1018` | The scheduled-energy record is 103 bytes. It includes the off-peak charging power setting. |
| `0x1026` | A separate 29-byte record carries the ordinary **Recharging Power** setting. |
| `0x102A` | A fresh `0x62` report verified the flat-rate electricity price and currency. The tested `0x60` read omitted this key. |

See [Auro energy and tariff records](packet-format.md#auro-energy-and-tariff-records)
and [Auro configuration writes](commands.md#auro-configuration-writes) for capture and readback details.

## 0x100D output-interface table

Power 1000 Mini has been observed to enumerate nested `0x1014` records for AC outlet, USB-C ports, USB-A ports, and SDC.

The current Mini capture contains six records in this order:

```text
AC
USB-C1
USB-C2
USB-A1
USB-A2
SDC1
```

The SDC record is confirmed to follow DJI Home's `SDC` control. Whether turning
it off also disables SDC input has not been established, so do not describe it
as output-only protocol behavior.

Power 2000 current captures may expose only AC outlet in this table even though the physical device has other ports. Therefore:

- presence in `0x100D` is strong evidence of a configurable interface;
- absence from `0x100D` is **not** proof that a physical capability does not exist.

## 0x101E charging-mode table

Power 1000 Mini reports self-describing `0x101F` records. Current verified options include:

```text
raw_id 1 -> slow -> nominal 500 W
raw_id 2 -> fast -> nominal 1000 W
```

The selected state is carried in each record. Prefer these device-reported nominal values to hard-coded UI assumptions.

## Scheduled-energy settings (0x1018)

Power 2000 reports an 86-byte record and Power Auro 2000 Elite reports a
103-byte record. Both profiles expose the scheduled-energy controls below.

Current confirmed control fields include scheduled/disabled energy mode, peak-discharge enable, off-peak-charge enable, off-peak charging power and min/max bounds.

Only the confirmed off-peak power field is changed by the writer. Other power-looking fields around offsets 30/34 and in the tail remain diagnostic-only candidates.

Power 2000's numeric entity uses a fixed verified model-profile step of 10 W.
Diagnostics compare that profile against the unresolved offset-34 candidate:

```text
off_peak_charging_power_step.configured_w
off_peak_charging_power_step.reported_0x1018_offset_34_candidate_w
off_peak_charging_power_step.candidate_matches_configured
```

Do not enable an unknown model or derive its write step solely from offset 34.

## Runtime mode gating

A static capability does not always mean a control should be available in the current device mode. Runtime feature availability is checked separately for off-peak charging, peak discharging, off-peak charging power, tariff period, and tariff time slots.

On Power 2000, confirmed energy optimization values are `disabled` and
`scheduled`. While disabled, off-peak charging, peak discharging, off-peak
charging power, and tariff time-slot controls are unavailable without changing
their entity-registry enabled state. `Tariff period` remains available and
reports `disabled`. Returning to `scheduled` reveals the values retained by the
device.

An unknown energy optimization value is preserved as raw/`unsupported`. Basic
telemetry remains active, but Scheduled-oriented 0x1018 writes are blocked so an
unrecognized mode is not overwritten.

Grid-Tied ESS read/write and the availability of Scheduled/TOU controls in that mode remain unimplemented.

## Power 2000 Scheduled-period power-flow behavior

**Confirmed in current Power 2000 field testing; implemented by station
firmware, not calculated by this integration**

When energy optimization mode is `scheduled`, current tests establish this
priority and behavior:

1. At `SoC <= discharge limit + 5%`, the station forces bypass supply when AC
   input is available. This protection behavior overrides the settings below.
2. With off-peak charging disabled, the station does not charge its battery
   from AC.
3. The off-peak charging-power value behaves as the AC-input maximum. If bypass
   load exceeds that maximum, the battery supplies the shortfall, subject to the
   protection rule above.
4. During a peak tariff period with peak discharging enabled, the station stops
   AC input without requiring an external smart plug. At or below the SoC
   protection threshold, it automatically resumes AC input for forced bypass.

These are device power-flow semantics observed on tested hardware. The
integration writes the confirmed settings and evaluates the reported tariff
table for Home Assistant display; it does not emulate these power-flow rules.
Revalidate after firmware changes before relying on them for unattended loads.

### Power 2000 off-peak input below the reported minimum

**Observed** on one Power 2000 with firmware `01.00.1500` on 2026-11-25.
At 8% SoC with zero output, the station drew 15–16 W before the test.
A one-off HA test selected all-day off-peak and sent a single `0x1018`
update enabling off-peak charging and requesting 300 W. The station's
reported minimum and maximum remained 600 W and 1500 W.

With the station temporarily excluded from HA surplus allocation, the
immediate `0x60` readback showed 300 W. At both 30 and 150 seconds it
showed 1050 W (the midpoint), with charging still enabled. AC inlet
power reached 306 W at 10 seconds and stayed within 298–302 W at every
10-second sample from 20 through 150 seconds. Total output stayed at
zero and reported SoC stayed at 8%. Battery-side power was not measured.
With allocation enabled in the first run, the reported setting had
returned to 600 W and charging was disabled by the 30-second readback.

The test established neither a minimum charging headroom under load nor
persistence over reconnection. The experimental override distinguishes the
requested wattage, the device-reported setting, and measured AC input.

### Off-peak minimum override across manual tariff preset changes

**Observed** in operator-reported hardware tests on 2026-11-26. On each
station the operator pressed **Set all-day peak tariff**, then **Set all-day
off-peak tariff**. The lower-bound override remained in effect on both.
After returning to off-peak, the operator verified that actual AC input was
capped at the selected **Off-peak charging power**: a setting in the mid-500 W
range on Power 2000 and 200 W on Power Auro 2000 Elite.

**Inferred (operator estimate):** During the Power 2000 test, the station
supplied about 200 W to the bypass load. The operator estimated that roughly
250–300 W went into battery charging. No direct battery-side power reading
was reported for this test.

Clock-driven transitions within an existing schedule remain open for testing.

### Power 2000 minimum AC input while charging with AC output off

**Observed** on a Power 2000 with one expansion battery attached. With AC
output off and no bypass load, a 200 W off-peak charging power request drew
229–230 W at the AC inlet. The observed charging floor in this configuration
was about 230 W, measured on the AC side.

The operator suggests 250 W or higher as a practical override minimum for
this configuration. The floor for a Power 2000 without an expansion battery
remains unknown.

### Observed Power 2000 ultralow-SoC recovery cycle

**Observed in one diagnostic sequence; broader behavior is reported field
experience and remains unconfirmed**

One Power 2000 firmware `01.00.1500` sequence used Scheduled mode, all-day peak
tariff, peak discharging enabled, off-peak charging disabled, and a configured
discharge limit of 0%. After extended forced-bypass operation at very low SoC,
the station performed an AC protective charge and later returned to
peak-period battery discharge at 10%:

```text
normal peak-period discharge
  -> forced bypass at discharge limit + 5% (5% in this case)
  -> continued slow battery depletion while bypassing (reported behavior)
  -> ultralow-SoC protective charging
  -> continued protective charging after reported SoC reached 5%
  -> release at discharge limit + 10% (10% in this case)
  -> AC input stopped and peak-period battery discharge resumed
```

The operator recalls approximately 3% SoC near the beginning of this recovery,
but the diagnostic HMS history did not retain the simultaneous 0x61 snapshot,
so that starting SoC is not capture-confirmed. Alarm `0x28000038` was present
for about 5 minutes 26 seconds and cleared three seconds before a 5% charging
screenshot. It did not reappear during the observed 5%-to-10% charge or when
discharge resumed. No Home Assistant write was recorded, and common 0x62
configuration values were unchanged in reports captured during the event.

Reported Power 2000 field experience has so far associated DJI Home's Energy
Saver-unavailable state only with protective charging in either of these cases:

- periodic full-charge maintenance, observed about once per five full charges;
- forced recovery from ultralow SoC to `discharge limit + 10%`.

This field experience is useful but does not rule out other triggers. Treat the
10% release rule, periodicity, and association with the app banner as
model/firmware-specific observations until reproduced with synchronized 0x61,
0x66, power-flow, and app-state captures. See `unknowns.md`.

### Maintenance-charge diagnostic (2026-09-26)

**Observed:** on Power 2000 firmware `01.00.1500` / communication firmware
`03.03.0000`, operator-identified maintenance charging at 70% SoC coincides
with `0x3050[6] = 0x05` and `0x3020[4] = 1`. DJI Home explicitly displays
maintenance charging to 100% in a nearby screenshot. The latest 0x66 is empty,
and no maintenance-specific HMS ID is present in the retained history.
**Hypothesis:** value `05` is a maintenance-charge state/reason; this single
sample does not establish semantics across states, accessories, or models.
See the [detailed evidence](hms-codes.md#2026-09-26-maintenance-charge-observation).

## Rule for new models

When adding a model:

1. document the advertisement model code;
2. capture 0x60 and 0x61 behavior;
3. record which keys/tables are actually returned;
4. create conservative static capabilities;
5. enable writes only after full-table safety is understood;
6. add model-specific protocol tests;
7. update this file and `unknowns.md` in the same change.

## Power Auro 2000 Elite charging during bypass

**Observed** on a user's Power Auro 2000 Elite (2026-11-25). DJI Home's
**Recharging Power** setting controls power used to charge the battery. During
bypass, total AC input is the sum of bypass output and battery charging power.
When **Off-peak charging power** is set and active for the current scheduled
period, it caps that sum. Bypass output therefore counts toward the limit.

### Off-peak charging power below 200 W

**Observed** in an operator-reported Power Auro 2000 Elite test on 2026-11-28:

| Downstream AC load | Off-peak charging power setting | Observed power flow |
| --- | ---: | --- |
| No load | 190 W | The operator heard a relay click and AC inlet power dropped to 0 W. |
| Bypass load present | 0 W | AC inlet power dropped to 0 W while the battery supplied the entire load. |
| Bypass load present | 10 W | The AC inlet supplied 10 W and the battery supplied the rest of the load. |

**Hypothesis:** With no bypass load, Auro may require an off-peak setting of
at least 200 W to charge from AC. The exact cutoff remains unverified.
With a bypass load, the 0 W setting has a demonstrated use: the battery can
take over the entire load while AC output continues.

## Auro 2000 Elite and Mini port controls

**Observed** in the November 24 DJI Home captures and app tests: Auro has two
USB-A, three USB-C and two SDC ports. Mini has two USB-A, two USB-C and one
controllable SDC port. Port identities in the output table use interface types
3, 4 and 5 respectively and one-based indices. Mini keeps its existing SDC
control. SDC power telemetry describes the group aggregate.

Auro reports a 103-byte scheduled-energy record and a separate 29-byte charging
power record. In the November 25 HA diagnostics, charging power writes to 1440 W and
900 W were verified by 0x62. Auro uses a 13-byte realtime battery record
where Power 2000 uses 12 bytes (see [telemetry](telemetry.md)).
The operator also verified both tariff presets; separate BLE writes for GBP
and priced periods, followed by a single combined write, were verified via
0x62 and the Wi-Fi app display (see [commands](commands.md#auro-configuration-writes)). Mini energy-management
switches additionally require a matching device-reported record.
