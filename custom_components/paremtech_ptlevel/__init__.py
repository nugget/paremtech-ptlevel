"""ParemTech PTLevel integration.

Reads PTLevel tank-level receivers over the local network, with no cloud
dependency. Each config entry is one receiver and the transmitter paired
with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PLATFORMS, STORAGE_VERSION
from .coordinator import PTLevelCoordinator, storage_key
from .ptlevel import PTLevelClient
from .tank import TANK_SENSOR_KEYS, tank_sensor_keys

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

type PTLevelConfigEntry = ConfigEntry[PTLevelCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PTLevelConfigEntry) -> bool:
    """Set up a PTLevel receiver from a config entry.

    Tank sensors whose settings were removed leave the entity registry first,
    before the receiver is contacted, so clearing a setting takes effect even
    while the receiver is unreachable and setup is retrying.
    """
    _remove_unused_tank_sensors(hass, entry)
    client = PTLevelClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = PTLevelCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_unused_tank_sensors(hass: HomeAssistant, entry: PTLevelConfigEntry) -> None:
    """Remove tank sensors that the entry's options no longer provide.

    Their unique IDs are built from the receiver ID, which is the entry's
    unique ID, so this needs no answer from the receiver.
    """
    if entry.unique_id is None:
        return
    registry = er.async_get(hass)
    provided = tank_sensor_keys(entry.options)
    for key in TANK_SENSOR_KEYS:
        if key in provided:
            continue
        unique_id = f"{entry.unique_id}_{key}"
        if entity_id := registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, unique_id
        ):
            registry.async_remove(entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: PTLevelConfigEntry) -> bool:
    """Unload a PTLevel config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PTLevelConfigEntry) -> None:
    """Delete the stored last report when an entry is removed."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
