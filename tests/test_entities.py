from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from butterflymx import ButterflyMXAuthError, ButterflyMXConnectionError, Door
from homeassistant.components.lock import LockState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.butterflymx.const import DOMAIN


async def test_sensor_states(hass, setup_integration):
    msg = hass.states.get("sensor.unit_101_last_message")
    assert msg.state == "Package here"
    assert msg.attributes["source"] == "Front Lobby"
    assert msg.attributes["entity_picture"] == "https://img.example/m1"

    call = hass.states.get("sensor.unit_101_last_call")
    assert call.state == "Front Lobby - MISSED"
    assert call.attributes["type"] == "VISITOR"

    access = hass.states.get("sensor.unit_101_last_access")
    assert access.state == "Garage - TENANT"
    assert access.attributes["method"] == "SWIPE_TO_OPEN"


async def test_sensors_update_from_coordinator(hass, setup_integration, mock_client):
    original = mock_client.tenant.get_overview.side_effect

    def newer():
        overview = original()
        overview.calls[0].status = "OPENED_DOOR"
        return overview

    mock_client.tenant.get_overview.side_effect = newer
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.unit_101_last_call").state == "Front Lobby - OPENED_DOOR"


async def test_offline_door_is_unavailable(hass, setup_integration):
    assert hass.states.get("lock.unit_101_front_lobby").state == LockState.LOCKED
    assert hass.states.get("lock.unit_101_garage").state == STATE_UNAVAILABLE


async def unlock(hass, entity_id="lock.unit_101_front_lobby"):
    await hass.services.async_call("lock", "unlock", {ATTR_ENTITY_ID: entity_id}, blocking=True)


@pytest.fixture
def door_open():
    with patch.object(Door, "open", new_callable=AsyncMock) as m:
        yield m


async def test_unlock_opens_door_then_relocks(hass, setup_integration, door_open):
    await unlock(hass)

    door_open.assert_awaited_once()
    assert hass.states.get("lock.unit_101_front_lobby").state == LockState.UNLOCKED

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert hass.states.get("lock.unit_101_front_lobby").state == LockState.LOCKED


async def test_unlock_cooldown(hass, setup_integration, door_open):
    await unlock(hass)
    with pytest.raises(HomeAssistantError, match="just opened"):
        await unlock(hass)
    assert door_open.await_count == 1


async def test_unlock_failure_raises(hass, setup_integration, door_open):
    door_open.side_effect = ButterflyMXConnectionError("timeout")
    with pytest.raises(HomeAssistantError, match="Failed to open"):
        await unlock(hass)
    assert hass.states.get("lock.unit_101_front_lobby").state == LockState.LOCKED


async def test_unlock_auth_failure_starts_reauth(hass, setup_integration, door_open):
    door_open.side_effect = ButterflyMXAuthError("revoked")
    with pytest.raises(HomeAssistantError):
        await unlock(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1


async def test_image_serves_octet_stream_snapshot_as_jpeg(hass, aioclient_mock, setup_integration, hass_client):
    aioclient_mock.get(
        "https://img.example/m1", content=b"\xff\xd8jpeg", headers={"Content-Type": "binary/octet-stream"}
    )
    state = hass.states.get("image.unit_101_latest_message_image")
    assert state is not None

    client = await hass_client()
    resp = await client.get(state.attributes["entity_picture"])

    assert resp.status == 200
    assert resp.content_type == "image/jpeg"
    assert await resp.read() == b"\xff\xd8jpeg"


async def test_image_is_cached_per_url(hass, aioclient_mock, setup_integration, hass_client):
    aioclient_mock.get("https://img.example/c1", content=b"img", headers={"Content-Type": "image/jpeg"})
    url = hass.states.get("image.unit_101_latest_call_image").attributes["entity_picture"]
    client = await hass_client()
    await client.get(url)
    await client.get(url)
    assert aioclient_mock.call_count == 1
