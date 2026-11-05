"""ParemTech PTLevel integration.

Reads PTLevel tank-level receivers over the local network, with no cloud
dependency. Each config entry is one receiver and the transmitter paired
with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import PLATFORMS, STORAGE_VERSION
from .coordinator import PTLevelCoordinator, storage_key
from .ptlevel import PTLevelClient

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

type PTLevelConfigEntry = ConfigEntry[PTLevelCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PTLevelConfigEntry) -> bool:
    """Set up a PTLevel receiver from a config entry."""
    client = PTLevelClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = PTLevelCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PTLevelConfigEntry) -> bool:
    """Unload a PTLevel config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PTLevelConfigEntry) -> None:
    """Delete the stored last report when an entry is removed."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
