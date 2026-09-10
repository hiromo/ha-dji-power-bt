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

## Historical record

- [`release-history.md`](release-history.md): version-by-version technical changes
  formerly kept in the root README.

The historical record can describe behavior that was later replaced. When it
conflicts with a topical current-design document, the topical document and the
current implementation are authoritative; investigate and update both if they
disagree.
