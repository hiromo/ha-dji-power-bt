# ADR 0007: Reset the public integration identity and config-entry baseline

## Status

Accepted.

## Context

During development, config-entry versions 2 through 8 accumulated migrations
for experimental stored data and entity unique IDs. The integration had not yet
been published for general use, so those versions did not represent a public
compatibility contract.

Pre-public code first used domain `dji_power` and later
`dji_power_bluetooth`. Before publication, the shorter technical identifier
`dji_power_bt` was selected as the permanent public domain while the
user-facing integration name remains DJI Power Bluetooth. Home Assistant does
not migrate Config Entries between integration domains automatically.

Keeping the development-only migrations would make the first public release
appear to inherit compatibility obligations that no public installation could
have relied on. Home Assistant also does not support normal config-entry
downgrades: an entry stored with a version higher than the config flow version is
rejected before the integration migration handler is called.

## Decision

- Start the public integration domain at `dji_power_bt` and package it as
  `custom_components/dji_power_bt`.
- Retire pre-public domains `dji_power` and `dji_power_bluetooth` without an
  in-place Config Entry, Device Registry, Entity Registry, or service-domain
  migration.
- Start the public config-entry schema at `ConfigFlow.VERSION = 1`.
- Keep all entity and config-entry unique ID values used by the current code.
- Remove the pre-public `async_migrate_entry()` implementation and its migration
  tests.
- Do not support in-place conversion of development entries stored with versions
  2 through 8. Development installations must delete and recreate those entries.
- Require explicit migrations, documentation, and tests for compatibility changes
  made after the first public release.

## Consequences

The public compatibility history is simple and begins with domain `dji_power_bt`
and config-entry version 1. Existing development entries under `dji_power` or
`dji_power_bluetooth`, including version 8 entries, cannot load under the new
baseline and must be removed through the Home Assistant UI and registered again.
Services move from `dji_power.*` or `dji_power_bluetooth.*` to `dji_power_bt.*`,
and Device Registry identifiers use the new domain. Removing an entry can
discard entity customizations, so development users should back up Home
Assistant and verify dashboard and automation references afterward.
