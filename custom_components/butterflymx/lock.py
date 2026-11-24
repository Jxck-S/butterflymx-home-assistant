"""Lock entities for ButterflyMX doors."""

from __future__ import annotations

import time
from typing import Any

from butterflymx import ButterflyMXAuthError, ButterflyMXError, Door
from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .auth import VERIFICATION_EXCEPTIONS, ensure_reauth_flow, get_pending_verification, stash_pending_verification
from .coordinator import ButterflyMXConfigEntry
from .entity import ButterflyMXEntity

# Doors re-lock themselves; show "unlocked" this long after opening
UNLOCKED_DISPLAY_SECONDS = 10
# Ignore repeat unlocks within this window
UNLOCK_COOLDOWN_SECONDS = 20


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ButterflyMXConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a lock entity for each door."""
    coordinator = entry.runtime_data
    async_add_entities(
        ButterflyMXDoor(coordinator, tenant, door)
        for tenant in coordinator.tenants
        for door in coordinator.data[tenant.id].doors
    )


class ButterflyMXDoor(ButterflyMXEntity, LockEntity):
    """A ButterflyMX door. Unlocking opens it; it re-locks on its own."""

    def __init__(self, coordinator, tenant, door: Door) -> None:
        super().__init__(coordinator, tenant)
        self._door = door
        self._attr_name = door.name
        self._attr_unique_id = f"butterflymx_door_{door.id}"
        self._attr_is_locked = True
        self._last_unlock = 0.0
        self._cancel_relock = None

    @property
    def available(self) -> bool:
        """Available when the coordinator is healthy and the door is online."""
        if not super().available:
            return False
        door = next((d for d in self.overview.doors if d.id == self._door.id), None)
        return bool(door and door.online)

    async def async_lock(self, **kwargs: Any) -> None:
        """Doors lock automatically; nothing to do."""

    def _verification_pending(self) -> bool:
        return get_pending_verification(self.hass, self.coordinator.config_entry.entry_id) is not None

    def _hold_for_verification(self, err: Exception) -> None:
        """Keep the session that already texted a code, and stop polling for another."""
        stash_pending_verification(self.hass, self.coordinator.config_entry.entry_id, self.coordinator.client, err)
        self.coordinator.update_interval = None
        ensure_reauth_flow(self.hass, self.coordinator.config_entry)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Open the door."""
        if self._verification_pending():
            ensure_reauth_flow(self.hass, self.coordinator.config_entry)
            raise HomeAssistantError(f"Failed to open {self.name}: verification required")

        remaining = UNLOCK_COOLDOWN_SECONDS - (time.monotonic() - self._last_unlock)
        if remaining > 0:
            raise HomeAssistantError(f"{self.name} was just opened; try again in {int(remaining) + 1}s")

        try:
            await self._door.open()
        except VERIFICATION_EXCEPTIONS as err:
            self._hold_for_verification(err)
            raise HomeAssistantError(f"Failed to open {self.name}: verification required") from err
        except ButterflyMXAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"Failed to open {self.name}: {err}") from err
        except ButterflyMXError as err:
            raise HomeAssistantError(f"Failed to open {self.name}: {err}") from err

        self._last_unlock = time.monotonic()
        self._attr_is_locked = False
        self.async_write_ha_state()
        if self._cancel_relock:
            self._cancel_relock()
        self._cancel_relock = async_call_later(self.hass, UNLOCKED_DISPLAY_SECONDS, self._relock)

    @callback
    def _relock(self, _now) -> None:
        self._cancel_relock = None
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_relock:
            self._cancel_relock()
        await super().async_will_remove_from_hass()
