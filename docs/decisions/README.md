# Architecture decision records

Read the relevant ADR before simplifying code that looks more complicated than necessary. Several safeguards exist because simpler implementations failed on real BLE hardware/proxy lifecycles.

| ADR | Decision |
|---|---|
| `0001-markdown-is-source-of-truth.md` | Repository Markdown is the persistent engineering memory |
| `0002-persistent-gatt-and-fresh-advertisement-reconnect.md` | Keep persistent GATT and use fresh-advertisement reconnect gating |
| `0003-read-modify-write-and-verification.md` | Separate 0x63 ACK completion from state verification |
| `0004-conservative-capability-gating.md` | Gate writes/entities conservatively by model/runtime/table completeness |
| `0005-preserve-unknown-protocol-data.md` | Preserve unknown protocol data and uncertainty instead of guessing |
| `0006-use-home-assistant-bluetooth-dependencies.md` | Use HA Bluetooth dependencies instead of pinning a private connector version |
| `0007-reset-public-config-entry-baseline.md` | Start public identity at domain `dji_power_bt` and config-entry version 1 |

Add an ADR when a future agent would otherwise be likely to remove an important non-obvious constraint.
