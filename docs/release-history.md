# Release history

Public release notes are in the [changelog](../CHANGELOG.md). The public
config-entry compatibility baseline is version 1 from v0.7.31. Before
publication, development-only migrations for versions 2–8 were removed.
Those development entries require recreation. See [ADR 0007](decisions/0007-reset-public-config-entry-baseline.md).

## Development milestones

- AC power sensors adopted inlet and outlet directions in v0.7.5. The earlier
  grid-port naming assumed a particular installation topology.
- From v0.7.6, BLE recovery retained disconnected clients for cleanup and
  required a settle delay and a fresh advertisement before reconnecting.
- v0.7.30 distinguished GATT reconnections from sessions returning to ready.
  Existing diagnostic consumers retained the GATT-side aliases.
- v0.7.32 suppressed redundant setting writes and isolated queued writes and
  notifications by BLE session.
