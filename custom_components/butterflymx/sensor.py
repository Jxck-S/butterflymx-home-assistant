import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import timedelta

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5) # Poll every 5 mins

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ButterflyMX Sensor platform."""
    client = hass.data[DOMAIN][entry.entry_id]
    tenants = await client.get_tenants()
    
    entities = []
    for tenant in tenants:
        entities.append(LastMessageSensor(client, tenant))
        entities.append(LastCallSensor(client, tenant))
            
    async_add_entities(entities, update_before_add=True)

class LastMessageSensor(SensorEntity):
    """Sensor for the latest message."""

    def __init__(self, client, tenant):
        self._client = client
        self._tenant = tenant
        self._attr_name = f"Last Message ({tenant.name})"
        self._attr_unique_id = f"butterflymx_last_message_{tenant.id}"
        self._attr_icon = "mdi:message-text"

    async def async_update(self):
        """Fetch latest messages."""
        msgs = await self._tenant.get_messages()
        if msgs:
            last_msg = msgs[0] # Assuming sorted desc by API, based on earlier observation
            self._attr_native_value = last_msg.body[:255] # HA state limit
            self._attr_extra_state_attributes = {
                "source": last_msg.source,
                "timestamp": last_msg.created_at,
                "full_body": last_msg.body
            }

class LastCallSensor(SensorEntity):
    """Sensor for the latest call."""

    def __init__(self, client, tenant):
        self._client = client
        self._tenant = tenant
        self._attr_name = f"Last Call ({tenant.name})"
        self._attr_unique_id = f"butterflymx_last_call_{tenant.id}"
        self._attr_icon = "mdi:phone"

    async def async_update(self):
        """Fetch latest calls."""
        calls = await self._tenant.get_calls()
        if calls:
             last_call = calls[0]
             self._attr_native_value = f"{last_call.device} - {last_call.status}"
             self._attr_extra_state_attributes = {
                 "status": last_call.status,
                 "device": last_call.device,
                 "type": last_call.type,
                 "timestamp": last_call.logged_at,
                 "image_url": last_call.image_url
             }
