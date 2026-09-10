# Protocol documentation index

This directory is the persistent source of truth for reverse-engineered DJI Power BLE protocol knowledge.

Do not read every protocol document automatically. Start here, then read only the files relevant to the change.

## Evidence labels

Use these labels consistently:

- **Confirmed**: repeated device behavior plus implementation/tests/captures support the semantic meaning.
- **Observed**: exact bytes or behavior were captured, but the semantic meaning is incomplete.
- **Inferred**: evidence strongly favors one interpretation but does not prove it.
- **Hypothesis**: an explanation to test.
- **Unknown**: deliberately uninterpreted.

A field may be safe to parse diagnostically while remaining unsafe to use for control.

## Document map

`transport.md`
: BLE characteristics and how application frames are carried over GATT.

`authentication.md`
: Pair keys, setup-time credential acquisition, and 0x6A authentication.

`packet-format.md`
: DUM-like framing, CRCs, transport version field, TLV/keyed-record structure, and provisional 0x66 structure.

`commands.md`
: Command set `0x5A`, commands `0x60`, `0x61`, `0x62`, `0x63`, `0x66`, and `0x6A`, including read/write/ACK behavior.

`telemetry.md`
: Battery and power telemetry, interface/group semantics, HMS observations, and fast-path rules.

`model-differences.md`
: Known model codes, static capability hints, device-reported feature signals, and behavior that must not be generalized across models.

`unknowns.md`
: Unresolved fields, protocol-version candidates beyond the DUM transport version, HMS code observations, and recommended experiments.

## General reverse-engineering rules

1. Keep raw bytes available in tests or diagnostics when practical.
2. Separate packet shape from semantic interpretation.
3. Do not assume a field is universal because two models share it.
4. Do not infer write safety from read parse success.
5. When nested tables contain unknown records or malformed tails, retain the unknown bytes and disable table write-back.
6. Prefer exact-address device identity. Advertised names are diagnostic, not identity.
7. Keep external connection labels neutral: use `ac_inlet` and `ac_outlet`, not `grid`, because the connected source/sink is not encoded by the port name.
8. Keep XT60 and SDC distinct. SDC may carry external MPPT or accessory traffic; XT60 support is retained for SDC accessory cable use and reported interface/group type 8/6 data.

## Current major protocol layers

```text
BLE advertisement
  -> DJI manufacturer data 0x08AA

GATT
  -> C304 write
  -> C305 notify

DUM-like frame
  -> command set 0x5A

Application commands
  -> config / telemetry / writes / HMS / authentication

Nested keyed records / TLVs
  -> model and feature-specific fields
```
