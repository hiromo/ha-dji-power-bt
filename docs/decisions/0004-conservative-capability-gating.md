# ADR 0004: Conservative capability and runtime gating

## Status

Accepted.

## Context

Power 2000 and Power 1000 Mini share transport and many records but expose different configuration keys and controls. Power 1000 and Power 1000 V2 are less thoroughly verified. A parsed field on one model is not proof of safe control on another.

## Decision

- Use conservative static capability profiles by advertisement model code for entity creation.
- Use runtime-mode availability separately from static capability.
- Treat device-returned 0x60 key/table presence as additional evidence, not automatic write authorization.
- Permit table writes only when the complete expected table is parsed with no unknown tail/record.
- Unknown model codes receive conservative defaults.

## Consequences

Some real device capabilities may remain hidden until verified, but the integration avoids exposing destructive or misleading controls based on weak inference.
