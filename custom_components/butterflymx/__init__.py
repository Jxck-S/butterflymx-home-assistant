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

from .auth import VERIFICATION_EXCEPTIONS, VERIFICATION_MESSAGE, get_pending_verification, stash_pending_verification
from .call_webhook import async_remove_call_webhook, async_setup_call_webhook
from .const import CONF_BMX_INTEGRATIONS, CONF_EMAIL, CONF_PASSWORD, CONF_TOKENS
from .coordinator import ButterflyMXConfigEntry, ButterflyMXCoordinator
from .event import async_remove_seen_calls

PLATFORMS = [Platform.EVENT, Platform.IMAGE, Platform.LOCK, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ButterflyMXConfigEntry) -> bool:
    """Set up ButterflyMX from a config entry.

    Saved tokens are passed in and written back when they refresh. The client
    uses those before it ever submits the password. A password login can text
    a verification code; retrying setup would text another one, so that failure
    is an auth failure and the open session is kept for the reauth step.
    """
    if get_pending_verification(hass, entry.entry_id) is not None:
        raise ConfigEntryAuthFailed(VERIFICATION_MESSAGE)

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
    except VERIFICATION_EXCEPTIONS as err:
        stash_pending_verification(hass, entry.entry_id, client, err)
        raise ConfigEntryAuthFailed(VERIFICATION_MESSAGE) from err
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
    # Instant alerts when Home Assistant Cloud is available; polling continues regardless
    await async_setup_call_webhook(hass, entry, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ButterflyMXConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ButterflyMXConfigEntry) -> None:
    """Delete the ButterflyMX webhook integration and the cloudhook when the entry is deleted.

    Uses the saved tokens; the client refreshes them itself if needed.
    """
    client = None
    if entry.data.get(CONF_BMX_INTEGRATIONS) and entry.data.get(CONF_TOKENS):
        client = ButterflyMXClient(
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
            session=async_get_clientsession(hass),
            tokens=entry.data.get(CONF_TOKENS),
        )
    await async_remove_call_webhook(hass, entry, client)
    await async_remove_seen_calls(hass, entry.entry_id)


def _remove_file(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
