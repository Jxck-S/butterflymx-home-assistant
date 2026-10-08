"""Sensors for the latest ButterflyMX message, call and door release."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ButterflyMXConfigEntry
from .entity import ButterflyMXEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ButterflyMXConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the ButterflyMX sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for tenant in coordinator.tenants:
        entities += [
            LastMessageSensor(coordinator, tenant),
            LastCallSensor(coordinator, tenant),
            LastAccessSensor(coordinator, tenant),
        ]
    async_add_entities(entities)


class LastMessageSensor(ButterflyMXEntity, SensorEntity):
    """The latest text message."""

    _attr_icon = "mdi:message-text"

    def __init__(self, coordinator, tenant) -> None:
        super().__init__(coordinator, tenant)
        self._attr_name = f"Last Message ({tenant.name})"
        self._attr_unique_id = f"butterflymx_last_message_{tenant.id}"

    @property
    def native_value(self) -> str | None:
        msgs = self.overview.messages
        return (msgs[0].body or "")[:255] if msgs else None

    @property
    def entity_picture(self) -> str | None:
        msgs = self.overview.messages
        return msgs[0].image_url if msgs else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not (msgs := self.overview.messages):
            return None
        m = msgs[0]
        return {
            "visitor_name": m.visitor_name,
            "source": m.source,
            "timestamp": dt_util.parse_datetime(m.created_at) if m.created_at else None,
            "image_url": m.image_url,
            "full_body": m.body,
            "summary": f"{m.visitor_name}: {m.body}",
        }


class LastCallSensor(ButterflyMXEntity, SensorEntity):
    """The latest intercom call."""

    _attr_icon = "mdi:phone"

    def __init__(self, coordinator, tenant) -> None:
        super().__init__(coordinator, tenant)
        self._attr_name = f"Last Call ({tenant.name})"
        self._attr_unique_id = f"butterflymx_last_call_{tenant.id}"

    @property
    def native_value(self) -> str | None:
        calls = self.overview.calls
        return f"{calls[0].device} - {calls[0].status}" if calls else None

    @property
    def entity_picture(self) -> str | None:
        calls = self.overview.calls
        return calls[0].image_url if calls else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not (calls := self.overview.calls):
            return None
        c = calls[0]
        return {
            "call_id": c.id,
            "status": c.status,
            "device": c.device,
            "type": c.type,
            "timestamp": dt_util.parse_datetime(c.logged_at) if c.logged_at else None,
            "image_url": c.image_url,
            "summary": f"{c.device} ({c.type}): {c.status}",
        }


class LastAccessSensor(ButterflyMXEntity, SensorEntity):
    """The latest door release."""

    _attr_icon = "mdi:door-open"

    def __init__(self, coordinator, tenant) -> None:
        super().__init__(coordinator, tenant)
        self._attr_name = f"Last Access ({tenant.name})"
        self._attr_unique_id = f"butterflymx_last_access_{tenant.id}"

    @property
    def native_value(self) -> str | None:
        logs = self.overview.access_logs
        return f"{logs[0].door_name} - {logs[0].type}" if logs else None

    @property
    def entity_picture(self) -> str | None:
        logs = self.overview.access_logs
        return logs[0].image_url if logs else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not (logs := self.overview.access_logs):
            return None
        a = logs[0]
        return {
            "access_id": a.id,
            "type": a.type,
            "method": a.method,
            "door": a.door_name,
            "device": a.device_name,
            "timestamp": dt_util.parse_datetime(a.logged_at) if a.logged_at else None,
            "image_url": a.image_url,
            "summary": f"{a.door_name} opened via {a.method} ({a.type})",
        }
