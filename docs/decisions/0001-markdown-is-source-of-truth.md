# ADR 0001: Repository Markdown is the source of truth

## Status

Accepted.

## Context

The project is reverse engineered and has accumulated important distinctions between confirmed behavior, observations, inferences, and hypotheses. AI-agent chat context is temporary and can omit earlier constraints.

## Decision

Repository Markdown under `AGENTS.md` and `docs/` is the persistent engineering memory.

- All agents, including Claude Code, read `AGENTS.md` directly as the canonical instruction file, which routes them to focused documents.
- Detailed protocol knowledge lives under `docs/protocol/`.
- Implementation constraints live under `docs/implementation/`.
- Non-obvious architectural choices live under `docs/decisions/`.

Do not use bulk imports from `AGENTS.md`; agents should read only task-relevant documents.

## Consequences

Code changes that alter documented behavior must update Markdown in the same change. Chat memory may help locate a topic, but it does not override repository documentation.
