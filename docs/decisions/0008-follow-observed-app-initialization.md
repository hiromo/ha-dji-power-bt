# ADR 0008: App-style reads with an explicit initialization boundary

## Status

Accepted by operator decision on 2026-10-12; revised the same day after a later
capture demonstrated successful Mini GET-before-0x62 startup.

## Context

The October 9 capture showed report/ACK before GETs. The later October 12 capture
showed both report-first and GET-first sessions on the same Mini. Neither a
mandatory report gate nor a fixed model branch follows from this evidence.
See the [capture analysis](../implementation/app-startup-order-2026-10-12-capture.md).
First-0x61 arrival correlates with app GET timing but is not proven to trigger it.

Publishing metrics immediately after authentication allowed HA automations to
request settings before initialization completed. This was a possible interleaving,
not a proven cause of the captured reconnect failures.

## Decision

- Keep two session requests, key authentication, two 61-byte GETs, two 0x1001
  GETs, and two 0x1004 GETs, on initial connection and reconnect.
- Remove the mandatory 0x62 wait and its timeout. Start reads after authentication;
  do not introduce an unproven 0x61 wait as a replacement.
- Keep sequential request/response matching and existing reconnect safeguards.
- Continue parsing notifications and sending required best-effort 0x62 ACKs.
- Require full readiness for ordinary setting calls, including direct services.
  Reject premature operations rather than queueing them for later execution.
- Keep ordinary entities unavailable and hide received values/attributes until
  ready. Retain internal metrics/configuration, then publish latest state once.
- Preserve connection diagnostic/failure notifications and BLE enable control.
- Do not apply short table replies as complete snapshots or introduce new writes.

## Consequences

Startup no longer fails solely because an initial report is absent. Rejected
premature setting calls are visible errors; callers may retry after readiness.
Behavior tests cover report-present/absent startup, reconnect, every GET failure,
ACKs, cancellation/disconnect, premature service calls, and entity publication.
Real-device reconnect recovery after this revision remains unvalidated.
