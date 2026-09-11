# ADR 0007: Public identity and config-entry baseline

## Status

Accepted.

## Context

Before publication, experimental config-entry versions 2-8 and the domains
`dji_power` and `dji_power_bluetooth` accumulated migrations for stored data and
unique IDs. They created no public compatibility contract. Home Assistant does
not migrate entries between domains or pass a higher stored version to a lower
config-flow version for migration.

## Decision

- Publish as `custom_components/dji_power_bt` with domain `dji_power_bt`, the
  user-facing name DJI Power Bluetooth, and `ConfigFlow.VERSION = 1`.
- Preserve the current config-entry and entity unique IDs.
- Retire both old domains and versions 2-8 without config-entry, Device/Entity
  Registry, service-domain, or downgrade migration; remove their
  `async_migrate_entry()` code and tests. Development users must delete and
  recreate those entries.
- Require migrations, documentation, and tests for later compatibility changes.

## Consequences

Public compatibility begins at `dji_power_bt`, version 1. Old development
entries cannot load and must be removed in the Home Assistant UI, then registered
again. Services move from `dji_power.*` or `dji_power_bluetooth.*` to
`dji_power_bt.*`; Device Registry identifiers use the new domain. Development
users should back up Home Assistant and recheck entity customizations, dashboards,
and automations after recreation.
