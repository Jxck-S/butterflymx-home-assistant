"""Instant call alerts through the ButterflyMX tenant webhook and a Home Assistant Cloud cloudhook."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from butterflymx import Call
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.butterflymx.const import (
    CONF_BMX_INTEGRATIONS,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    CONF_WEBHOOK_URL,
    SCAN_INTERVAL,
    WEBHOOK_SECRET_HEADER,
)

ENTITY = "event.unit_101_intercom_call"
CLOUDHOOK = "https://hooks.nabu.casa/test-hook"
LIST_URL = "https://api.butterflymx.com/v4/tenants/1/integrations"
OUR_URL = f"{CLOUDHOOK}?tenant=1"


@pytest.fixture
def cloud(hass):
    """A logged-in, connected Home Assistant Cloud."""
    fake = SimpleNamespace(
        async_active_subscription=MagicMock(return_value=True),
        async_is_connected=MagicMock(return_value=True),
        async_get_or_create_cloudhook=AsyncMock(return_value=CLOUDHOOK),
        async_delete_cloudhook=AsyncMock(),
        async_listen_connection_change=MagicMock(return_value=MagicMock()),
        CloudConnectionState=SimpleNamespace(CLOUD_CONNECTED="cloud_connected"),
    )
    hass.config.components.add("cloud")
    with patch("custom_components.butterflymx.call_webhook._cloud", return_value=fake):
        yield {"create": fake.async_get_or_create_cloudhook, "delete": fake.async_delete_cloudhook, "fake": fake}


@pytest.fixture
def api_client(mock_client):
    mock_client.ensure_token = AsyncMock()
    mock_client.access_token = "api-token"
    mock_client.USER_AGENT = "test-agent"
    return mock_client


async def _setup(hass, config_entry):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def _rings(hass) -> list[dict]:
    fired: list[dict] = []

    @callback
    def record(event) -> None:
        new = event.data["new_state"]
        if event.data["entity_id"] == ENTITY and new and new.attributes.get("event_type") == "ring":
            fired.append(dict(new.attributes))

    hass.bus.async_listen("state_changed", record)
    return fired


def _delivery(logged_at: str | None = None) -> dict:
    """A call delivery timestamped now, so it is inside the freshness window."""
    return {
        "event": {
            "resource_type": "call",
            "action": "create",
            "data": {
                "id": 555,
                "guid": "g-555",
                "logged_at": logged_at or dt_util.utcnow().isoformat(),
                "notification_type": "visitor",
                "panel_name": "Main Entrance",
                "image_url": "https://img.example/555",
            },
        }
    }


async def test_setup_creates_call_webhook_once(hass, config_entry, api_client, cloud, aioclient_mock):
    aioclient_mock.get(LIST_URL, json={"data": []})
    aioclient_mock.post(LIST_URL, json={"data": {"id": "77", "type": "integrations"}})
    await _setup(hass, config_entry)

    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert len(posts) == 1
    body = posts[0][2]
    attrs = body["data"]["attributes"]
    assert attrs["integrator"] == "webhook"
    assert attrs["configuration"]["url"] == OUR_URL
    assert attrs["configuration"]["method"] == "post"
    assert attrs["configuration"]["headers"] == {WEBHOOK_SECRET_HEADER: config_entry.data[CONF_WEBHOOK_SECRET]}
    assert attrs["bindings"] == [{"resource_type": "call", "actions": ["create"]}]
    assert posts[0][3]["Authorization"] == "Bearer api-token"
    assert len(config_entry.data[CONF_WEBHOOK_SECRET]) >= 40
    assert config_entry.data[CONF_WEBHOOK_URL] == CLOUDHOOK
    assert config_entry.data[CONF_BMX_INTEGRATIONS] == {"tenant-1": "77"}
    cloud["create"].assert_awaited_once_with(hass, config_entry.data[CONF_WEBHOOK_ID])


async def test_secret_never_logged(hass, config_entry, api_client, cloud, aioclient_mock, caplog):
    aioclient_mock.get(LIST_URL, json={"data": []})
    aioclient_mock.post(LIST_URL, status=422, json={"errors": [{"detail": "echo"}]})
    caplog.set_level("DEBUG")
    await _setup(hass, config_entry)
    assert "Couldn't set up the ButterflyMX call webhook" in caplog.text
    assert config_entry.data[CONF_WEBHOOK_SECRET] not in caplog.text


async def test_existing_webhook_is_reused_not_duplicated(hass, config_entry, api_client, cloud, aioclient_mock):
    aioclient_mock.get(
        LIST_URL,
        json={
            "data": [
                {"id": "12", "attributes": {"configuration": {"url": "https://elsewhere.example/hook"}}},
                {"id": "34", "attributes": {"configuration": {"url": OUR_URL}}},
            ]
        },
    )
    await _setup(hass, config_entry)
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert config_entry.data[CONF_BMX_INTEGRATIONS] == {"tenant-1": "34"}


async def test_existing_webhook_in_live_list_shape_is_reused(hass, config_entry, api_client, cloud, aioclient_mock):
    """The real list endpoint returns flat items with `config`, not `attributes.configuration`."""
    aioclient_mock.get(
        LIST_URL,
        json={
            "data": [
                {"id": "a-1", "config": {"url": "https://elsewhere.example/hook"}, "integrator": "webhook"},
                {"id": "b-2", "config": {"method": "post", "url": OUR_URL}, "integrator": "webhook"},
            ]
        },
    )
    await _setup(hass, config_entry)
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert config_entry.data[CONF_BMX_INTEGRATIONS] == {"tenant-1": "b-2"}


async def test_without_cloud_only_polls(hass, config_entry, api_client, aioclient_mock):
    with patch("custom_components.butterflymx.call_webhook.cloud_ready", return_value=False):
        await _setup(hass, config_entry)
    assert aioclient_mock.call_count == 0
    assert CONF_WEBHOOK_ID not in config_entry.data
    assert hass.states.get(ENTITY) is not None


async def test_create_failure_keeps_polling(hass, config_entry, api_client, cloud, aioclient_mock):
    aioclient_mock.get(LIST_URL, status=500)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert CONF_BMX_INTEGRATIONS not in config_entry.data
    assert hass.states.get(ENTITY) is not None


async def _linked(hass, config_entry, aioclient_mock):
    aioclient_mock.get(LIST_URL, json={"data": []})
    aioclient_mock.post(LIST_URL, json={"data": {"id": "77"}})
    await _setup(hass, config_entry)


async def test_good_secret_fires_ring_immediately(
    hass, config_entry, api_client, cloud, aioclient_mock, hass_client_no_auth
):
    await _linked(hass, config_entry, aioclient_mock)
    rings = _rings(hass)
    delivery = _delivery()
    client = await hass_client_no_auth()
    resp = await client.post(
        f"/api/webhook/{config_entry.data[CONF_WEBHOOK_ID]}?tenant=1",
        json=delivery,
        headers={WEBHOOK_SECRET_HEADER: config_entry.data[CONF_WEBHOOK_SECRET]},
    )
    assert resp.status == 200
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(rings) == 1
    ring = rings[0]
    assert ring["call_id"] == "prod-call-555"
    assert ring["status"] == "INITIALIZING"
    assert ring["type"] == "VISITOR"
    assert ring["device"] == "Main Entrance"
    assert ring["logged_at"] == delivery["event"]["data"]["logged_at"]
    assert ring["image_url"] == "https://img.example/555"


@pytest.mark.parametrize("headers", [{}, {WEBHOOK_SECRET_HEADER: "wrong"}])
async def test_bad_secret_is_rejected(
    hass, config_entry, api_client, cloud, aioclient_mock, hass_client_no_auth, headers
):
    await _linked(hass, config_entry, aioclient_mock)
    rings = _rings(hass)
    overview_calls = api_client.tenant.get_overview.await_count
    client = await hass_client_no_auth()
    resp = await client.post(
        f"/api/webhook/{config_entry.data[CONF_WEBHOOK_ID]}?tenant=1", json=_delivery(), headers=headers
    )
    assert resp.status == 401
    await hass.async_block_till_done(wait_background_tasks=True)
    assert rings == []
    assert api_client.tenant.get_overview.await_count == overview_calls  # no refresh either


async def test_duplicate_delivery_and_later_poll_fire_once(
    hass, config_entry, api_client, cloud, aioclient_mock, hass_client_no_auth
):
    await _linked(hass, config_entry, aioclient_mock)
    rings = _rings(hass)
    client = await hass_client_no_auth()
    delivery = json.dumps(_delivery())
    for _ in range(2):  # ButterflyMX retries deliveries
        resp = await client.post(
            f"/api/webhook/{config_entry.data[CONF_WEBHOOK_ID]}?tenant=1",
            data=delivery,
            headers={WEBHOOK_SECRET_HEADER: config_entry.data[CONF_WEBHOOK_SECRET]},
        )
        assert resp.status == 200
    await hass.async_block_till_done(wait_background_tasks=True)

    # The poll then sees the same call under its GraphQL id
    original = api_client.tenant.get_overview.side_effect

    def with_call():
        overview = original()
        overview.calls = [
            Call({"id": "prod-call-555", "displayStatus": "OPENED_DOOR", "device": {"name": "Main Entrance"}}),
            *overview.calls,
        ]
        return overview

    api_client.tenant.get_overview.side_effect = with_call
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [r["call_id"] for r in rings] == ["prod-call-555"]


async def test_door_release_delivery_does_not_ring(
    hass, config_entry, api_client, cloud, aioclient_mock, hass_client_no_auth
):
    await _linked(hass, config_entry, aioclient_mock)
    rings = _rings(hass)
    client = await hass_client_no_auth()
    resp = await client.post(
        f"/api/webhook/{config_entry.data[CONF_WEBHOOK_ID]}?tenant=1",
        json={"event": {"resource_type": "door_release", "action": "create", "data": {"id": 9}}},
        headers={WEBHOOK_SECRET_HEADER: config_entry.data[CONF_WEBHOOK_SECRET]},
    )
    assert resp.status == 200
    await hass.async_block_till_done(wait_background_tasks=True)
    assert rings == []


async def test_remove_deletes_integration_and_cloudhook(hass, config_entry, api_client, cloud, aioclient_mock):
    await _linked(hass, config_entry, aioclient_mock)
    webhook_id = config_entry.data[CONF_WEBHOOK_ID]
    aioclient_mock.delete(f"{LIST_URL}/77", status=204)

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    deletes = [c for c in aioclient_mock.mock_calls if c[0] == "DELETE"]
    assert [str(c[1]) for c in deletes] == [f"{LIST_URL}/77"]
    cloud["delete"].assert_awaited_once_with(hass, webhook_id)


async def test_remove_survives_api_failure(hass, config_entry, api_client, cloud, aioclient_mock):
    await _linked(hass, config_entry, aioclient_mock)
    aioclient_mock.delete(f"{LIST_URL}/77", status=500)
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    cloud["delete"].assert_awaited_once()


async def test_waits_for_cloud_connection_after_restart(hass, config_entry, api_client, cloud, aioclient_mock):
    """Cloud logged in but not yet connected: link once it connects."""
    cloud["fake"].async_is_connected.return_value = False
    aioclient_mock.get(LIST_URL, json={"data": []})
    aioclient_mock.post(LIST_URL, json={"data": {"id": "77"}})
    await _setup(hass, config_entry)
    assert CONF_BMX_INTEGRATIONS not in config_entry.data

    on_change = cloud["fake"].async_listen_connection_change.call_args[0][1]
    on_change("cloud_connected")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.data[CONF_BMX_INTEGRATIONS] == {"tenant-1": "77"}
