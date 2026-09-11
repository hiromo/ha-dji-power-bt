# Engineering documentation

Repository Markdown is the persistent engineering record for this integration.
Use the topical documents below for the current behavior. Use the release history
only when the reason for an older migration or compatibility rule matters.

## Public documentation

- [`../README.md`](../README.md): installation, supported hardware, normal use,
  model-specific behavior, Bluetooth troubleshooting, and secret-handling
  guidance for users.
- [`../CHANGELOG.md`](../CHANGELOG.md): concise user-visible changes for public
  releases.
- [`../LICENSE`](../LICENSE): Apache License 2.0 terms for the project.
- [GitHub Releases](https://github.com/hiromo/ha-dji-power-bt/releases):
  release notes presented to GitHub and HACS users.

## Current design

- [`architecture.md`](architecture.md): runtime ownership, module boundaries,
  concurrency, compatibility surfaces, and testing layers.
- [`protocol/README.md`](protocol/README.md): protocol evidence labels and the
  protocol-document map.
- [`implementation/home-assistant.md`](implementation/home-assistant.md): config
  entries, entities, services, migrations, availability, and diagnostics.
- [`implementation/bluetooth-lifecycle.md`](implementation/bluetooth-lifecycle.md):
  BLE client ownership, setup, disconnect, and reconnect behavior.
- [`implementation/connection-diagnostics.md`](implementation/connection-diagnostics.md):
  diagnostic JSON structure, scopes, field semantics, event correlation, and
  redaction boundaries for Bluetooth connection troubleshooting.
- [`implementation/error-handling.md`](implementation/error-handling.md): failure
  semantics, write errors, diagnostic counters, and redaction.
- [`decisions/README.md`](decisions/README.md): accepted architecture decisions
  that should not be undone without new evidence.

## History and incident evidence

- [`release-history.md`](release-history.md): version-by-version technical changes
  formerly kept in the root README.
- [`implementation/ble-disconnect-investigation-2026-09-11.md`](implementation/ble-disconnect-investigation-2026-09-11.md):
  retained incident timeline, evidence, and hypotheses.
- [`implementation/ble-comparison-and-review-2026-09-11.md`](implementation/ble-comparison-and-review-2026-09-11.md):
  comparison, decisions, and validation for version 0.7.32.

Open incident records only when that evidence is relevant. History may describe
replaced behavior; topical documents and current code are authoritative. If they
disagree, investigate and update both.
