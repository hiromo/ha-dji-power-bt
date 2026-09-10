# DJI Power Bluetooth Home Assistant integration: agent instructions

This repository implements a local Bluetooth Home Assistant integration for DJI Power devices.

Treat repository Markdown as the persistent source of truth. Do not treat chat transcripts, prior agent memory, or unstated assumptions as authoritative. When code and documentation disagree, stop, investigate, and update the documentation and code together.

Keep this file concise. Detailed technical knowledge belongs under `docs/`.

Do not bulk-read or automatically import every file under `docs/`. Read only the documents required for the change you are making.

## Before making changes

- Read `docs/architecture.md` before changing module boundaries, shared state ownership, runtime data flow, or public manager interfaces.
- Read `docs/decisions/README.md` before undoing or simplifying a non-obvious design choice.
- Preserve the public import surface of `custom_components.dji_power_bt.protocol` unless the change explicitly includes a compatibility migration.
- Preserve config-entry compatibility unless the change explicitly includes and tests a migration.

## Protocol framing, parsing, and generation

Before modifying DUM-like framing, CRCs, sequence handling, TLV scanning, packet parsing, packet generation, command IDs, or protocol constants, read:

- `docs/protocol/README.md`
- `docs/protocol/packet-format.md`
- `docs/protocol/commands.md`

Before changing a field whose meaning is not fully confirmed, also read:

- `docs/protocol/unknowns.md`

## Authentication and pair keys

Before modifying pair-key validation, DJI account/member-token flows, command `0x6A`, session establishment, or authentication payloads, read:

- `docs/protocol/authentication.md`
- `docs/protocol/commands.md`
- `docs/implementation/error-handling.md`

Never add authentication command `0x6A`, pair keys, member tokens, account passwords, or equivalent secrets to payload capture or diagnostics.

## Bluetooth transport and lifecycle

Before modifying BLE discovery, exact-address resolution, GATT characteristics, connection setup, notification subscription, disconnect cleanup, retries, reconnect behavior, stale-connection cleanup, or shared connection locking, read:

- `docs/protocol/transport.md`
- `docs/implementation/bluetooth-lifecycle.md`
- `docs/implementation/connection-diagnostics.md`
- `docs/decisions/0002-persistent-gatt-and-fresh-advertisement-reconnect.md`
- `docs/decisions/0006-use-home-assistant-bluetooth-dependencies.md`

Do not remove the fresh-advertisement reconnect gate, the unexpected-disconnect settle delay, retired-client cleanup, weak-reference expected-disconnect tracking, or the domain-wide connection-operation lock as a cleanup unless the replacement is justified by new evidence and behavior tests.

## Configuration reads, writes, and verification

Before modifying `0x60`, `0x62`, or `0x63` handling; read-modify-write logic; cache policy; ACK handling; write verification; tariff writes; charging-mode writes; or output-interface writes, read:

- `docs/protocol/commands.md`
- `docs/protocol/model-differences.md`
- `docs/decisions/0003-read-modify-write-and-verification.md`
- `docs/decisions/0004-conservative-capability-gating.md`

Do not write a partially understood nested table. Preserve unknown records, or refuse the write when the current code cannot prove that the table is complete.

## Telemetry, HMS, and measurements

Before adding or changing decoded measurements, power-direction semantics, HMS parsing, or `0x61`/`0x66` handling, read:

- `docs/protocol/telemetry.md`
- `docs/protocol/model-differences.md`
- `docs/protocol/unknowns.md`

Do not rename AC inlet/outlet directions back to a grid-specific interpretation. The protocol describes device ports, not the external energy source or sink connected to them.

Do not remove XT60 or SDC telemetry because a currently tested device does not report it. These paths are intentionally retained for supported accessories and model variants.

## Home Assistant entities, services, diagnostics, and migrations

Before adding, removing, renaming, enabling, disabling, or changing the availability of entities or services, read:

- `docs/implementation/home-assistant.md`
- `docs/protocol/model-differences.md`

Before changing diagnostic keys, redaction, payload capture, error categories, or connection counters, also read:

- `docs/implementation/error-handling.md`

Before changing config-entry data or entity unique IDs, inspect the current config-entry compatibility code, ADR 0007, and release-contract tests. After the public version 1 baseline, do not change `ConfigFlow.VERSION` without a migration.

## Model-specific behavior

Before introducing or changing model-specific logic, read:

- `docs/protocol/model-differences.md`
- `docs/protocol/unknowns.md`
- `docs/decisions/0004-conservative-capability-gating.md`

Never assume behavior observed on one DJI Power model applies to another. Prefer device-reported configuration records when their semantics are confirmed, and keep static model capabilities conservative.

## Reverse engineering

Before interpreting a new field, command, flag, model difference, or protocol-version candidate, read:

- `docs/protocol/README.md`
- `docs/protocol/packet-format.md`
- `docs/protocol/model-differences.md`
- `docs/protocol/unknowns.md`
- `docs/decisions/0005-preserve-unknown-protocol-data.md`

Classify every new conclusion as one of:

- **Confirmed**: implementation meaning is supported by repeated device behavior and tests/captures.
- **Observed**: raw bytes or device behavior were observed, but semantic meaning is not established.
- **Inferred**: evidence strongly suggests a meaning, but a competing explanation remains possible.
- **Hypothesis**: a useful theory that still needs targeted evidence.
- **Unknown**: deliberately not interpreted.

Do not silently promote an observation, inference, or hypothesis into a write-path assumption.

When new reverse-engineering knowledge is established, update the corresponding Markdown in the same change:

- packet/frame discoveries -> `docs/protocol/packet-format.md`
- command behavior -> `docs/protocol/commands.md`
- telemetry/HMS fields -> `docs/protocol/telemetry.md`
- model differences -> `docs/protocol/model-differences.md`
- unresolved fields and experiments -> `docs/protocol/unknowns.md`
- architectural choices that future agents may otherwise undo -> add or update an ADR under `docs/decisions/`

## Testing requirements

Run focused tests while developing and the full suite before declaring a change complete.

```bash
python -m pytest -q
python -m compileall -q custom_components tests
```

For protocol changes, add byte-level parser/builder tests. For connection changes, add behavior tests that execute lifecycle paths; do not rely only on source-text assertions. For write changes, test ACK failure, passive verification, readback fallback where applicable, and unknown-record safety. For entity/config-entry changes, preserve release-contract coverage and migration coverage for migrations from a public baseline.

Do not claim real-device validation unless it was actually performed outside the agent environment and the evidence is recorded.
