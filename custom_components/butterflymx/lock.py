import logging
from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ButterflyMX Lock platform."""
    client = hass.data[DOMAIN][entry.entry_id]

    # Fetch tenants and doors
    tenants = await client.get_tenants()
    
    entities = []
    for tenant in tenants:
        doors = await tenant.get_doors()
        for door in doors:
            entities.append(ButterflyMXDoor(client, door, tenant))
            
    async_add_entities(entities)

class ButterflyMXDoor(LockEntity):
    """Representation of a ButterflyMX Door."""

    def __init__(self, client, door, tenant):
        self._client = client
        self._door = door
        self._tenant = tenant
        self._attr_name = f"{door.name} ({tenant.name})"
        self._attr_unique_id = f"butterflymx_door_{door.id}"
        
        # It's an access control system, so we assume it's "locked" unless we are actively opening it.
        # But LockEntity expects a state.
        self._attr_is_locked = True
        self._last_unlock_time = 0

    async def async_lock(self, **kwargs):
        """Lock the door (Not supported/Auto-locks)."""
        pass

    async def async_unlock(self, **kwargs):
        """Unlock the door."""
        import time
        now = time.time()
        if now - self._last_unlock_time < 20:
            _LOGGER.warning(f"Unlock requested for {self.name} but cooldown is active ({int(20 - (now - self._last_unlock_time))}s remaining)")
            return

        _LOGGER.info(f"Unlocking {self.name}")
        self._last_unlock_time = now
        
        # Call the async open() method
        success = await self._door.open()
        
        if success:
             self._attr_is_locked = False
             self.async_write_ha_state()
             
             # Re-lock after 'openDuration' (simulated) or just immediately since we can't really track it
             # For now, we rely on the next update or just keep it unlocked for a moment visually?
             # Better: just set it back to locked after a delay, but let's leave it simple.
             self._attr_is_locked = True
             self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if door is online."""
        return self._door.online
