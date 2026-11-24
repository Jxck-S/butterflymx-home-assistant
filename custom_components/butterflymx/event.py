"""Event entity that fires once for each new ButterflyMX intercom call.

ButterflyMX has no feed of new calls for a resident account: its only GraphQL
subscription (callStatusUpdates) needs the ID of a call that is still active,
which the official apps get from a push notification. New calls arrive two
ways: instantly from the tenant webhook (call_webhook.py) when Home Assistant
Cloud is available, and from the coordinator's poll either way. This entity
turns each new call into exactly one event, whichever way saw it first.

A call id is remembered on disk, so a restart, a config-entry reload, or a
poll that fails and then recovers cannot ring it again. Calls older than
CALL_FRESHNESS are history (the sensors still show them) and do not ring.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from butterflymx import Call
from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_WEBHOOK_CALL
from .coordinator import ButterflyMXConfigEntry
from .entity import ButterflyMXEntity

_LOGGER = logging.getLogger(__name__)

EVENT_RING = "ring"
# After a long outage, announce at most this many of the newest calls.
MAX_EVENTS_PER_UPDATE = 5
# Someone at the door is not news after this long. The window is wider than
# the 30s poll, a couple of missed polls, a short restart, and a little clock
# skew between ButterflyMX's logged_at and Home Assistant.
CALL_FRESHNESS = timedelta(minutes=3)
# Ids are small. Keeping the most recently seen ones is enough: anything
# older than the freshness window cannot ring even if its id is forgotten.
MAX_REMEMBERED_CALLS = 200
SEEN_CALLS = f"{DOMAIN}_seen_calls"

_ATTRS = ("call_id", "status", "type", "device", "logged_at", "image_url")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ButterflyMXConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an intercom call event entity for each tenant."""
    coordinator = entry.runtime_data
    async_add_entities(IntercomCallEvent(coordinator, tenant) for tenant in coordinator.tenants)


async def async_remove_seen_calls(hass: HomeAssistant, entry_id: str) -> None:
    """Delete remembered call ids when the config entry is removed."""
    stores: dict[str, SeenCalls] = hass.data.get(SEEN_CALLS) or {}
    store = stores.pop(entry_id, None)
    if store is None:
        store = SeenCalls(hass, entry_id)
    await store.async_remove()


def async_get_seen_calls(hass: HomeAssistant, entry_id: str) -> SeenCalls:
    """The remembered-call store for one config entry, kept across reloads."""
    stores: dict[str, SeenCalls] = hass.data.setdefault(SEEN_CALLS, {})
    store = stores.get(entry_id)
    if store is None:
        store = SeenCalls(hass, entry_id)
        stores[entry_id] = store
    return store


class SeenCalls:
    """Call ids that have already been decided, per tenant.

    Lives on hass.data so a config-entry reload sees the same set even if the
    disk write is still in flight. The file is what survives a process restart.
    Home Assistant's EventEntity already uses extra_restore_state_data for the
    last event type and attributes, and that cache is only snapshotted on
    unload or every 15 minutes, so it is the wrong place for this set.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._disk: Store[dict[str, dict[str, list[str]]]] = Store(hass, 1, f"{SEEN_CALLS}.{entry_id}")
        self._lock = asyncio.Lock()
        self._order: dict[str, list[str]] | None = None
        self._known: dict[str, set[str]] | None = None
        self._generation = 0
        self._saved_generation = 0
        self._task: asyncio.Task[None] | None = None

    async def async_load(self) -> None:
        """Read the file once. Later loads in this process reuse memory."""
        async with self._lock:
            if self._order is not None:
                return
            raw = await self._disk.async_load()
            order: dict[str, list[str]] = {}
            known: dict[str, set[str]] = {}
            for tenant_id, keys in ((raw or {}).get("calls") or {}).items():
                items = [str(key) for key in keys][-MAX_REMEMBERED_CALLS:]
                order[str(tenant_id)] = items
                known[str(tenant_id)] = set(items)
            self._order = order
            self._known = known

    def seen(self, tenant_id: str, key: str) -> bool:
        """Whether this call id was already decided for the tenant."""
        assert self._known is not None
        return key in self._known.get(tenant_id, ())

    def remember(self, tenant_id: str, keys: list[str]) -> list[str]:
        """Remember keys, oldest first. Returns the ones that were new.

        The list grows at the end. When it is over the cap, the front (the
        ids decided longest ago) is dropped.
        """
        assert self._order is not None and self._known is not None
        order = self._order.setdefault(tenant_id, [])
        known = self._known.setdefault(tenant_id, set())
        added: list[str] = []
        for key in keys:
            if key in known:
                continue
            order.append(key)
            known.add(key)
            added.append(key)
        trimmed = False
        if len(order) > MAX_REMEMBERED_CALLS:
            dropped = order[:-MAX_REMEMBERED_CALLS]
            del order[:-MAX_REMEMBERED_CALLS]
            dropped_set = set(dropped)
            for key in dropped:
                known.discard(key)
            # Don't report an id we immediately forgot; the caller would ring it.
            added = [key for key in added if key not in dropped_set]
            trimmed = True
        if added or trimmed:
            self._generation += 1
            self._kick()
        return added

    def _snapshot(self) -> dict[str, dict[str, list[str]]]:
        assert self._order is not None
        return {"calls": {tenant_id: list(keys) for tenant_id, keys in self._order.items()}}

    def _kick(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = self._hass.async_create_task(self._flush(), name="butterflymx_seen_calls")

    async def _flush(self) -> None:
        """Write the set. A call remembered during the write starts another save."""
        try:
            async with self._lock:
                while self._generation != self._saved_generation:
                    generation = self._generation
                    await self._disk.async_save(self._snapshot())
                    self._saved_generation = generation
        finally:
            self._task = None
        if self._generation != self._saved_generation:
            self._kick()

    async def async_flush(self) -> None:
        """Wait until every remembered id has been written."""
        while self._generation != self._saved_generation or (self._task is not None and not self._task.done()):
            self._kick()
            task = self._task
            if task is None:
                return
            await task

    async def async_remove(self) -> None:
        """Drop the file. Used when the config entry is deleted."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._task = None
        await self._disk.async_remove()


@dataclass(slots=True)
class _Incoming:
    key: str
    logged_at: str | None
    attributes: dict[str, str | None]


class IntercomCallEvent(ButterflyMXEntity, EventEntity):
    """Fires `ring` once per call, from the webhook or the poll, whichever is first."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [EVENT_RING]
    _attr_translation_key = "intercom_call"
    _attr_icon = "mdi:doorbell-video"

    def __init__(self, coordinator, tenant) -> None:
        super().__init__(coordinator, tenant)
        self._attr_name = "Intercom Call"
        self._attr_unique_id = f"butterflymx_intercom_call_{tenant.id}"
        self._store: SeenCalls | None = None
        self._closed = False

    @property
    def available(self) -> bool:
        """A failed poll does not take this entity offline.

        CoordinatorEntity would publish `unavailable` whenever the poll fails,
        then publish the last ring's timestamp again when the poll recovers.
        That state change is what a state trigger reads as a new ring. The
        last ring stays true while the poll is down. Sensors and locks still
        follow the coordinator, and a webhook can still publish a ring.
        """
        return True

    async def async_added_to_hass(self) -> None:
        self._store = async_get_seen_calls(self.hass, self.coordinator.config_entry.entry_id)
        await self._store.async_load()
        await self._adopt_restored_ring()
        await super().async_added_to_hass()
        signal = SIGNAL_WEBHOOK_CALL.format(entry_id=self.coordinator.config_entry.entry_id, tenant_id=self._tenant.id)
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_webhook_call))
        # The first refresh already ran, and the coordinator does not replay it.
        # State writes in this method are dropped: the platform has not marked
        # the entity added yet, so a burst would collapse into whichever ring
        # was last. Decide on the next loop, after that write has happened.
        self.hass.async_create_task(self._announce_loaded_calls(), eager_start=False)

    async def _announce_loaded_calls(self) -> None:
        if self._closed or self._store is None:
            return
        self._consider(self._from_poll(self.overview.calls), webhook=False)

    async def async_will_remove_from_hass(self) -> None:
        self._closed = True
        if self._store is not None:
            try:
                await self._store.async_flush()
            except Exception:
                _LOGGER.exception("Couldn't save which ButterflyMX calls have already rung")
        await super().async_will_remove_from_hass()

    async def _adopt_restored_ring(self) -> None:
        """Versions before the store kept only the last ring on the entity."""
        assert self._store is not None
        restored = await self.async_get_last_event_data()
        if restored is None or not restored.last_event_attributes:
            return
        call_id = restored.last_event_attributes.get("call_id")
        if call_id:
            self._store.remember(self._tenant.id, [call_key(str(call_id))])

    @callback
    def _handle_webhook_call(self, call: dict[str, str | None]) -> None:
        """A delivery from the ButterflyMX webhook. The poll won't fire it again."""
        incoming = self._from_webhook(call)
        if incoming is None:
            return  # no id to dedupe; the refresh this delivery triggers can fire it
        self._consider([incoming], webhook=True)

    @callback
    def _handle_coordinator_update(self) -> None:
        # A failed poll leaves the previous overview in place. Deciding again
        # from that copy cannot learn anything, and writing state here is how
        # a recovered poll used to republish the last ring.
        if not self.coordinator.last_update_success or self._store is None:
            return
        self._consider(self._from_poll(self.overview.calls), webhook=False)

    def _consider(self, incoming: list[_Incoming], *, webhook: bool) -> None:
        assert self._store is not None
        fresh: list[_Incoming] = []
        remember: list[str] = []
        batch: set[str] = set()
        for item in incoming:
            if not item.key or item.key in batch or self._store.seen(self._tenant.id, item.key):
                continue
            batch.add(item.key)
            if _is_fresh(item.logged_at, webhook=webhook):
                fresh.append(item)
            else:
                _LOGGER.debug(
                    "Not ringing for call %s; logged_at %s is outside %s",
                    item.key,
                    item.logged_at,
                    CALL_FRESHNESS,
                )
            remember.append(item.key)
        if not remember:
            return
        # Poll results are newest first. Of a burst, ring the newest few,
        # oldest of those first, and remember the rest so they never ring later.
        announce = fresh if webhook else list(reversed(fresh[:MAX_EVENTS_PER_UPDATE]))
        claimed = set(self._store.remember(self._tenant.id, list(reversed(remember))))
        rung: set[str] = set()
        for item in announce:
            if item.key not in claimed or item.key in rung:
                continue
            rung.add(item.key)
            self._trigger_event(EVENT_RING, item.attributes)
            self.async_write_ha_state()

    def _from_poll(self, calls: list[Call]) -> list[_Incoming]:
        return [_Incoming(call_key(call.id), call.logged_at, _attributes(call)) for call in calls if call.id]

    def _from_webhook(self, call: dict[str, str | None]) -> _Incoming | None:
        raw = call.get("id")
        if not raw:
            return None
        call_id = graphql_call_id(str(raw), self._tenant.id)
        attributes = {key: call.get(key) for key in _ATTRS}
        attributes["call_id"] = call_id
        return _Incoming(call_key(call_id), call.get("logged_at"), attributes)


def call_key(call_id: str) -> str:
    """Same key for the webhook's '277231292' and GraphQL's 'prod-call-277231292'."""
    match = re.fullmatch(r"(?:[a-z]+-call-)?(\d+)", str(call_id))
    return match.group(1) if match else str(call_id)


def graphql_call_id(call_id: str, tenant_id: str) -> str:
    """'277231292' -> 'prod-call-277231292', matching the poll's ids (environment from the tenant id)."""
    if not str(call_id).isdigit():
        return str(call_id)
    match = re.match(r"([a-z]+)-tenant-", str(tenant_id))
    return f"{match.group(1) if match else 'prod'}-call-{call_id}"


def _attributes(call: Call) -> dict[str, str | None]:
    return {
        "call_id": call.id,
        "status": call.status,
        "type": call.type,
        "device": call.device,
        "logged_at": call.logged_at,
        "image_url": call.image_url,
    }


def _is_fresh(logged_at: str | None, *, webhook: bool) -> bool:
    """True when this call is still worth announcing as someone at the door.

    A webhook with no timestamp is a live delivery. A poll row with no
    timestamp is not: there is nothing to tell it from history.
    """
    if not logged_at:
        return webhook
    parsed = dt_util.parse_datetime(logged_at)
    if parsed is None:
        return webhook
    try:
        age = dt_util.utcnow() - parsed
    except TypeError:
        return webhook
    return -CALL_FRESHNESS <= age <= CALL_FRESHNESS
