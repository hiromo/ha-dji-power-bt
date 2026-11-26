import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import test_manager_v070 as base


@pytest.fixture
def migrate(monkeypatch):
    monkeypatch.setattr(sys.modules["homeassistant.helpers"], "entity_registry", SimpleNamespace(
        async_get=lambda hass: hass.registry,
    ), raising=False)
    monkeypatch.setitem(sys.modules, "homeassistant.util", SimpleNamespace(
        slugify=lambda name: name.lower().replace(" ", "_"),
    ))
    module = importlib.import_module("custom_components.dji_power_bt.migration")
    return module.async_migrate_entry


@pytest.mark.parametrize(("domain", "old", "new"), [
    ("number", "charging_power", "recharging_power"),
    ("switch", "ac_output_auto_restore", "ac_output_auto_restoration"),
    ("switch", "ac_charging_cable_safety_check", "ac_recharging_cable_safety_check"),
])
@pytest.mark.parametrize("case", ["default", "custom", "occupied", "foreign", "migrated"])
def test_registry_migration(migrate, domain, old, new, case):
    entry = SimpleNamespace(version=1, minor_version=2 if case == "migrated" else 1,
                            entry_id="station", data={"address": base.TEST_BLE_ADDRESS},
                            title="DJI Power Auro 2000 Elite")
    prefix = f"{domain}.dji_power_auro_2000_elite_"
    old_id, new_id = prefix + old, prefix + new
    record = SimpleNamespace(platform="dji_power_bt",
                             config_entry_id="another" if case == "foreign" else "station",
                             unique_id=f"02_00_00_00_00_01_{old}")
    records = {f"{domain}.custom" if case == "custom" else old_id: record}
    if case == "occupied":
        records[new_id] = object()
    hass = Mock()
    hass.registry.async_get.side_effect = records.get
    hass.states.get.return_value = None
    assert asyncio.run(migrate(hass, entry))
    if case == "default":
        hass.registry.async_update_entity.assert_called_once_with(old_id, new_entity_id=new_id)
    else:
        hass.registry.async_update_entity.assert_not_called()
    if case != "migrated":
        hass.config_entries.async_update_entry.assert_called_once_with(entry, minor_version=2)
