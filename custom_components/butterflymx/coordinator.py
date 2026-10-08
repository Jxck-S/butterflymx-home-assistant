"""Data coordinator for ButterflyMX: one request per tenant per update."""

from __future__ import annotations

import logging

from butterflymx import (
    ButterflyMXAuthError,
    ButterflyMXClient,
    ButterflyMXError,
    Tenant,
    TenantOverview,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ButterflyMXConfigEntry = ConfigEntry[ButterflyMXCoordinator]


class ButterflyMXCoordinator(DataUpdateCoordinator[dict[str, TenantOverview]]):
    """Fetches doors, messages, calls and access logs for every tenant."""

    config_entry: ButterflyMXConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ButterflyMXConfigEntry,
        client: ButterflyMXClient,
        tenants: list[Tenant],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.tenants = tenants

    async def _async_update_data(self) -> dict[str, TenantOverview]:
        try:
            return {t.id: await t.get_overview() for t in self.tenants}
        except ButterflyMXAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ButterflyMXError as err:
            raise UpdateFailed(str(err)) from err
