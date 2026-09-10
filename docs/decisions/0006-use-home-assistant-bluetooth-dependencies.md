# ADR 0006: Use Home Assistant Bluetooth dependencies

## Status

Accepted.

## Context

A previous integration manifest pinned an older `bleak-retry-connector` version while Home Assistant Core required a newer version, causing setup incompatibility after a Core upgrade.

## Decision

Declare Home Assistant integration dependencies:

```json
"dependencies": ["bluetooth", "bluetooth_adapters"]
```

Do not add a duplicate strict `bleak-retry-connector` requirement to this custom integration. Import and use the connector APIs supplied through the Home Assistant environment.

## Consequences

Connector compatibility follows the Home Assistant Core Bluetooth stack. Test against supported HA versions instead of attempting to override Core's connector dependency.
