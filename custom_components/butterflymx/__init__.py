import logging
import os
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD

from .butterflymx import ButterflyMXClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["lock", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ButterflyMX from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Use HA's .storage directory for internal token files
    token_file = hass.config.path(".storage", f"butterflymx_tokens_{entry.entry_id}.json")

    client = ButterflyMXClient(
        email=entry.data[CONF_EMAIL], 
        password=entry.data[CONF_PASSWORD],
        token_file=token_file
    )

    # Initial Login
    success = await client.login()
    
    if not success:
        _LOGGER.error("Failed to login to ButterflyMX")
        return False

    hass.data[DOMAIN][entry.entry_id] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
