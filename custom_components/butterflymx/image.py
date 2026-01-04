import logging
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ButterflyMX Image platform."""
    client = hass.data[DOMAIN][entry.entry_id]
    tenants = await client.get_tenants()
    
    entities = []
    for tenant in tenants:
        entities.append(LatestCallImage(hass, tenant))
        entities.append(LatestMessageImage(hass, tenant))
        entities.append(LatestAccessImage(hass, tenant))
            
    async_add_entities(entities, update_before_add=True)

class ButterflyMXImageEntity(ImageEntity):
    """Base class for ButterflyMX image entities."""

    def __init__(self, hass: HomeAssistant, tenant) -> None:
        """Initialize the image entity."""
        super().__init__(hass)
        self._tenant = tenant
        self._attr_should_poll = True
        self._last_image_url = None

    @property
    def image_url(self) -> str | None:
        """Return the URL of the image."""
        return self._last_image_url

class LatestCallImage(ButterflyMXImageEntity):
    """Image entity for the latest call snapshot."""

    def __init__(self, hass, tenant):
        super().__init__(hass, tenant)
        self._attr_name = f"Latest Call Image ({tenant.name})"
        self._attr_unique_id = f"butterflymx_latest_call_image_{tenant.id}"

    async def async_update(self):
        """Update the image URL."""
        calls = await self._tenant.get_calls()
        if calls:
            new_url = calls[0].image_url
            if new_url != self._last_image_url:
                self._last_image_url = new_url
                self._attr_image_last_updated = dt_util.utcnow()

class LatestMessageImage(ButterflyMXImageEntity):
    """Image entity for the latest message snapshot."""

    def __init__(self, hass, tenant):
        super().__init__(hass, tenant)
        self._attr_name = f"Latest Message Image ({tenant.name})"
        self._attr_unique_id = f"butterflymx_latest_message_image_{tenant.id}"

    async def async_update(self):
        """Update the image URL."""
        msgs = await self._tenant.get_messages()
        if msgs:
            new_url = msgs[0].image_url
            if new_url != self._last_image_url:
                self._last_image_url = new_url
                self._attr_image_last_updated = dt_util.utcnow()

class LatestAccessImage(ButterflyMXImageEntity):
    """Image entity for the latest access event snapshot."""

    def __init__(self, hass, tenant):
        super().__init__(hass, tenant)
        self._attr_name = f"Latest Access Image ({tenant.name})"
        self._attr_unique_id = f"butterflymx_latest_access_image_{tenant.id}"

    async def async_update(self):
        """Update the image URL."""
        logs = await self._tenant.get_access_logs()
        if logs:
            last_log = logs[0]
            new_url = last_log.image_url
            if new_url != self._last_image_url:
                self._last_image_url = new_url
                self._attr_image_last_updated = dt_util.utcnow()
