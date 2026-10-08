"""The ButterflyMX integration."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from butterflymx import (
    ButterflyMXAuthError,
    ButterflyMXClient,
    ButterflyMXError,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKENS
from .coordinator import ButterflyMXConfigEntry, ButterflyMXCoordinator

PLATFORMS = [Platform.IMAGE, Platform.LOCK, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ButterflyMXConfigEntry) -> bool:
    """Set up ButterflyMX from a config entry."""

    def save_tokens(tokens: dict[str, Any]) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKENS: tokens})

    client = ButterflyMXClient(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
        tokens=entry.data.get(CONF_TOKENS),
        on_tokens_updated=save_tokens,
    )

    try:
        tenants = await client.get_tenants()
    except ButterflyMXAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except ButterflyMXError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = ButterflyMXCoordinator(hass, entry, client, tenants)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Versions before 2.0 kept tokens in a file under .storage; they live in the entry now
    old_token_file = hass.config.path(".storage", f"butterflymx_tokens_{entry.entry_id}.json")
    await hass.async_add_executor_job(_remove_file, old_token_file)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ButterflyMXConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _remove_file(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
