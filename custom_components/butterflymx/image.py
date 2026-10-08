"""Image entities for the latest ButterflyMX call, message and door release snapshots."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ButterflyMXConfigEntry, ButterflyMXCoordinator
from .entity import ButterflyMXEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ButterflyMXConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the ButterflyMX image entities."""
    coordinator = entry.runtime_data
    entities: list[ImageEntity] = []
    for tenant in coordinator.tenants:
        entities += [
            LatestCallImage(hass, coordinator, tenant),
            LatestMessageImage(hass, coordinator, tenant),
            LatestAccessImage(hass, coordinator, tenant),
        ]
    async_add_entities(entities)


class ButterflyMXImageEntity(ButterflyMXEntity, ImageEntity):
    """Shows the snapshot from the latest event of one kind."""

    _kind: str

    def __init__(self, hass: HomeAssistant, coordinator: ButterflyMXCoordinator, tenant) -> None:
        ButterflyMXEntity.__init__(self, coordinator, tenant)
        ImageEntity.__init__(self, hass)
        self._attr_name = f"Latest {self._kind.title()} Image"
        self._attr_unique_id = f"butterflymx_latest_{self._kind}_image_{tenant.id}"
        self._image: tuple[str, bytes] | None = None  # (url, bytes) cache
        self._update_url()

    def _latest(self) -> tuple[str | None, str | None]:
        """(snapshot URL, event time) of the latest event."""
        raise NotImplementedError

    def _update_url(self) -> None:
        url, event_time = self._latest()
        if url != self._attr_image_url:
            self._attr_image_url = url
            # The entity's state is this time, so use when the event happened,
            # not when Home Assistant first saw it
            self._attr_image_last_updated = (dt_util.parse_datetime(event_time) if event_time else None) or (
                dt_util.utcnow()
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_url()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Download the snapshot.

        Done here instead of relying on ImageEntity's URL loader because some
        ButterflyMX snapshots (messages) are served as binary/octet-stream,
        which that loader rejects.
        """
        url = self._attr_image_url
        if not url:
            return None
        if self._image and self._image[0] == url:
            return self._image[1]
        async with async_get_clientsession(self.hass).get(url) as resp:
            resp.raise_for_status()
            content = await resp.read()
            ctype = resp.content_type
        self._attr_content_type = ctype if ctype.startswith("image/") else "image/jpeg"
        self._image = (url, content)
        return content


class LatestCallImage(ButterflyMXImageEntity):
    _kind = "call"

    def _latest(self) -> tuple[str | None, str | None]:
        calls = self.overview.calls
        return (calls[0].image_url, calls[0].logged_at) if calls else (None, None)


class LatestMessageImage(ButterflyMXImageEntity):
    _kind = "message"

    def _latest(self) -> tuple[str | None, str | None]:
        msgs = self.overview.messages
        return (msgs[0].image_url, msgs[0].created_at) if msgs else (None, None)


class LatestAccessImage(ButterflyMXImageEntity):
    _kind = "access"

    def _latest(self) -> tuple[str | None, str | None]:
        logs = self.overview.access_logs
        return (logs[0].image_url, logs[0].logged_at) if logs else (None, None)
