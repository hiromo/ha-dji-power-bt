"""Migrations for public DJI Power Bluetooth config entries."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import CONF_ADDRESS, CONF_DEVICE_NAME, DOMAIN
from .protocol import normalize_address

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rename the three original default entity IDs in public version 1.1."""
    if entry.version != 1:
        return False
    if entry.minor_version != 1:
        return True

    registry = er.async_get(hass)
    device_slug = slugify(entry.data.get(CONF_DEVICE_NAME) or entry.title)
    address_key = normalize_address(entry.data[CONF_ADDRESS]).replace(":", "_").lower()
    for domain, old_key, new_key in (
        ("number", "charging_power", "recharging_power"),
        ("switch", "ac_output_auto_restore", "ac_output_auto_restoration"),
        ("switch", "ac_charging_cable_safety_check", "ac_recharging_cable_safety_check"),
    ):
        old_id = f"{domain}.{device_slug}_{old_key}"
        entity = registry.async_get(old_id)
        if (
            entity is None
            or entity.config_entry_id != entry.entry_id
            or entity.platform != DOMAIN
            or entity.unique_id != f"{address_key}_{old_key}"
        ):
            continue

        new_id = f"{domain}.{device_slug}_{new_key}"
        if registry.async_get(new_id) is not None or hass.states.get(new_id) is not None:
            _LOGGER.warning("Keeping %s because %s is already in use", old_id, new_id)
            continue
        registry.async_update_entity(old_id, new_entity_id=new_id)

    hass.config_entries.async_update_entry(entry, minor_version=2)
    return True
