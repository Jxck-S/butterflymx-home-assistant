"""Base entity for ButterflyMX."""

from __future__ import annotations

from butterflymx import Tenant, TenantOverview
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ButterflyMXCoordinator


class ButterflyMXEntity(CoordinatorEntity[ButterflyMXCoordinator]):
    """An entity belonging to one tenant (unit). Named "<unit> <entity name>"."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ButterflyMXCoordinator, tenant: Tenant) -> None:
        super().__init__(coordinator)
        self._tenant = tenant
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tenant.id)},
            name=tenant.name,
            manufacturer="ButterflyMX",
        )

    @property
    def overview(self) -> TenantOverview:
        return self.coordinator.data.get(self._tenant.id) or TenantOverview()
