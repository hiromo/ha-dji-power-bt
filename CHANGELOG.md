# Changelog

This file records user-visible changes to public releases of DJI Power
Bluetooth. Detailed pre-public engineering history remains in
[`docs/release-history.md`](docs/release-history.md).

The project follows the principle of keeping a changelog: entries describe
notable user impact rather than every internal code change.

## Unreleased

- Added `dji_power_bt.set_tariff_schedule` for complete Power 2000 tariff-table
  replacement using an all-day preset or a detailed weekday/time period list.
- Removed the standalone `Tariff schedule profile` entity. Its read-only
  classification is now the `preset_match` attribute of `Tariff time slots`;
  the two disabled-by-default all-day buttons remain as convenience wrappers
  around the new action.
- Renamed the pre-public integration domain to `dji_power_bt` and the GitHub
  repository to `ha-dji-power-bt`; the user-facing name remains DJI Power
  Bluetooth.
- Added HACS custom-repository metadata, installation instructions, and
  automated HACS/Hassfest validation.
- Reorganized and translated the public documentation into English.
- Documented verified Power 2000 Scheduled-period behavior, tariff presets, the
  combined scheduled-energy action, Bluetooth capacity/reconnect behavior, and
  pair-key security and recovery guidance.
- Clarified that DJI Home conflicts only when it occupies the same station's
  Bluetooth connection; Wi-Fi and cloud access can remain active.
- Added the Apache License 2.0 project license and documented the sustained
  real-environment testing period that began in early June 2026.

## Public release baseline

The first public compatibility baseline uses integration domain
`dji_power_bt`, manifest version `0.7.31`, and Home Assistant config-entry
version `1`. Pre-public config-entry versions and the retired `dji_power` domain
and `dji_power_bluetooth` domain are development history and are not supported
migration sources.

Published version notes will also be available from
[GitHub Releases](https://github.com/hiromo/ha-dji-power-bt/releases).
