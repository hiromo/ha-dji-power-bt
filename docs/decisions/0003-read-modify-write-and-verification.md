# ADR 0003: Read-modify-write and separate state verification

## Status

Accepted.

## Context

DJI setting payloads often contain tables and fields that are only partly understood. A 0x63 response proves transaction completion but does not necessarily prove that a later reported device state matches the requested value. High-frequency automation can also write more often than a periodic 0x62 report arrives.

## Decision

- Build writes from a recent device-reported configuration snapshot.
- Use a 30-second general config cache and 15-second output-table cache where safe.
- Modify only confirmed fields.
- Preserve companion/unknown data required by known payload shape.
- Treat matching 0x63 ACK/result code zero as request completion.
- Record an optimistic local value for responsive HA state, but keep verification pending.
- Prefer subsequent 0x62 reports for verification.
- Low-frequency writes may perform one delayed 0x60 readback after 12 seconds if passive verification did not arrive.
- High-frequency off-peak power writes do not force a readback per write; they wait up to 20 seconds for passive 0x62 confirmation.
- Unknown or incomplete nested 0x100D/0x101E tables disable write-back rather than dropping unknown records.
- Coalesce unchanged targets across individual and bulk setters after range,
  mode, table-completeness, and snapshot-freshness checks. An ACK-backed
  optimistic value may coalesce a duplicate while its verification is pending,
  without declaring it confirmed. If verification expires without a device
  report, allow another request. Preserve unknown table records even when
  deciding whether the requested operation is a no-op.

## Consequences

BLE traffic stays low under automation, while write failures and stale assumptions remain visible. The implementation is intentionally more complex than "send write and assume success".
