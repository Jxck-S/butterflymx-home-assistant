"""Fixtures for ButterflyMX integration tests.

The ButterflyMX client is mocked; these tests exercise the integration's
behavior inside a real Home Assistant test instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from butterflymx import Access, Call, Door, Message, TenantOverview
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.butterflymx.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKENS, DOMAIN

EMAIL = "user@example.com"
PASSWORD = "hunter2"
TOKENS = {"access_token": "a", "refresh_token": "r", "expires_at": 9999999999}
TENANT_ID = "tenant-1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def make_overview(client) -> TenantOverview:
    return TenantOverview(
        doors=[
            Door({"id": "ap-1", "name": "Front Lobby", "online": True}, tenant_id=TENANT_ID, client=client),
            Door({"id": "ap-2", "name": "Garage", "online": False}, tenant_id=TENANT_ID, client=client),
        ],
        messages=[
            Message({"id": "m-1", "body": "Package here", "createdAt": "2026-01-02T00:00:00Z",
                     "imageUrl": "https://img.example/m1", "origin": "VISITOR", "source": {"name": "Front Lobby"}})
        ],
        calls=[
            Call({"id": "c-1", "loggedAt": "2026-01-03T00:00:00Z", "displayStatus": "MISSED",
                  "notificationType": "VISITOR", "imageUrl": "https://img.example/c1",
                  "device": {"name": "Front Lobby"}})
        ],
        access_logs=[
            Access({"id": "a-1", "loggedAt": "2026-01-04T00:00:00Z", "imageUrl": "https://img.example/a1",
                    "type": "TENANT", "method": "SWIPE_TO_OPEN", "accessPoint": {"name": "Garage"},
                    "device": {"name": "Garage Panel"}})
        ],
    )


@pytest.fixture
def mock_client():
    """Patch ButterflyMXClient everywhere the integration creates one."""
    client = MagicMock()
    client.tokens = TOKENS
    client.login = AsyncMock()

    tenant = MagicMock()
    tenant.id = TENANT_ID
    tenant.name = "Unit 101"
    tenant.get_overview = AsyncMock(side_effect=lambda: make_overview(client))
    client.get_tenants = AsyncMock(return_value=[tenant])
    client.tenant = tenant

    def factory(*args, **kwargs):
        client.init_kwargs = kwargs
        return client

    with (
        patch("custom_components.butterflymx.ButterflyMXClient", side_effect=factory),
        patch("custom_components.butterflymx.config_flow.ButterflyMXClient", side_effect=factory),
    ):
        yield client


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD, CONF_TOKENS: TOKENS},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(hass, config_entry, mock_client):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
