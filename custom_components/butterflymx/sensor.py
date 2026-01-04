import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import timedelta
from homeassistant.util import dt as dt_util


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
        entities.append(LastAccessSensor(client, tenant))
            
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
            last_msg = msgs[0]
            self._attr_native_value = last_msg.body[:255]
            self._attr_entity_picture = last_msg.image_url
            
            ts = dt_util.parse_datetime(last_msg.created_at)
            
            self._attr_extra_state_attributes = {
                "visitor_name": last_msg.visitor_name,
                "source": last_msg.source,
                "timestamp": ts,
                "image_url": last_msg.image_url,
                "full_body": last_msg.body,
                "summary": f"{last_msg.visitor_name}: {last_msg.body}"
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
             self._attr_entity_picture = last_call.image_url
             
             ts = dt_util.parse_datetime(last_call.logged_at)

             self._attr_extra_state_attributes = {
                 "call_id": last_call.id,
                 "status": last_call.status,
                 "device": last_call.device,
                 "type": last_call.type,
                 "timestamp": ts,
                 "image_url": last_call.image_url,
                 "summary": f"{last_call.device} ({last_call.type}): {last_call.status}"
             }


class LastAccessSensor(SensorEntity):
    """Sensor for the latest door release."""

    def __init__(self, client, tenant):
        self._client = client
        self._tenant = tenant
        self._attr_name = f"Last Access ({tenant.name})"
        self._attr_unique_id = f"butterflymx_last_access_{tenant.id}"
        self._attr_icon = "mdi:door-open"

    async def async_update(self):
        """Fetch latest door releases."""
        logs = await self._tenant.get_access_logs()
        if logs:
            last_log = logs[0]
            self._attr_native_value = f"{last_log.door_name} - {last_log.type}"
            self._attr_entity_picture = last_log.image_url
            
            ts = dt_util.parse_datetime(last_log.logged_at)

            self._attr_extra_state_attributes = {
                "access_id": last_log.id,
                "type": last_log.type,
                "method": last_log.method,
                "door": last_log.door_name,
                "device": last_log.device_name,
                "timestamp": ts,
                "image_url": last_log.image_url,
                "summary": f"{last_log.door_name} opened via {last_log.method} ({last_log.type})"
            }


