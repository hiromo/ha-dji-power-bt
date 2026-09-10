# ADR 0005: Preserve unknown protocol data and uncertainty

## Status

Accepted.

## Context

The protocol is reverse engineered. Several records contain fields that look like power ratings, feature flags, versions, or status codes but do not yet have controlled evidence.

## Decision

- Preserve useful raw unknown bytes in diagnostics where safe.
- Name candidate fields as candidates/unknowns, not production semantics.
- Keep strict nested-table parsing and retain unparsed tails.
- Refuse writes that could delete unknown records.
- Document observations, inferences, hypotheses, and unknowns distinctly.
- Keep experimental HMS/status fields diagnostic-only until their meaning is reproduced.

## Consequences

Diagnostics may contain extra raw/candidate data, and some implementation paths remain intentionally incomplete. This is preferred to silently baking a wrong reverse-engineering assumption into user controls.
