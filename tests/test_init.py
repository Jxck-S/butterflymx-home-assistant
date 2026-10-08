from datetime import timedelta

from butterflymx import ButterflyMXAuthError, ButterflyMXConnectionError
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.butterflymx.const import CONF_TOKENS, DOMAIN

from .conftest import TOKENS


async def test_setup_creates_entities(hass, setup_integration, mock_client):
    assert setup_integration.state is ConfigEntryState.LOADED
    ids = set(hass.states.async_entity_ids())
    assert {
        "sensor.unit_101_last_message",
        "sensor.unit_101_last_call",
        "sensor.unit_101_last_access",
        "image.unit_101_latest_call_image",
        "image.unit_101_latest_message_image",
        "image.unit_101_latest_access_image",
        "lock.unit_101_front_lobby",
        "lock.unit_101_garage",
    } <= ids
    # One overview request per tenant, not one per entity
    assert mock_client.tenant.get_overview.await_count == 1


async def test_client_gets_shared_session_and_saved_tokens(hass, setup_integration, mock_client):
    kwargs = mock_client.init_kwargs
    assert kwargs["session"] is not None
    assert kwargs["tokens"] == TOKENS
    assert callable(kwargs["on_tokens_updated"])


async def test_token_updates_saved_to_entry(hass, setup_integration, mock_client):
    new = {"access_token": "new", "refresh_token": "new-r", "expires_at": 123}
    mock_client.init_kwargs["on_tokens_updated"](new)
    assert setup_integration.data[CONF_TOKENS] == new


async def test_auth_error_starts_reauth(hass, config_entry, mock_client):
    mock_client.get_tenants.side_effect = ButterflyMXAuthError("bad password")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_connection_error_retries_setup(hass, config_entry, mock_client):
    mock_client.get_tenants.side_effect = ButterflyMXConnectionError("offline")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_update_failure_marks_entities_unavailable(hass, setup_integration, mock_client):
    mock_client.tenant.get_overview.side_effect = ButterflyMXConnectionError("offline")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.unit_101_last_call").state == STATE_UNAVAILABLE


async def test_auth_failure_during_update_starts_reauth(hass, setup_integration, mock_client):
    mock_client.tenant.get_overview.side_effect = ButterflyMXAuthError("revoked")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_old_token_file_is_removed(hass, config_entry, mock_client):
    path = hass.config.path(".storage", f"butterflymx_tokens_{config_entry.entry_id}.json")
    await hass.async_add_executor_job(_write, path)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert not await hass.async_add_executor_job(_exists, path)


async def test_unload(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


def _write(path):
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{}")


def _exists(path):
    import os

    return os.path.exists(path)


async def test_existing_entity_ids_kept_on_upgrade(hass, config_entry, mock_client):
    """Entities registered by 1.x keep their entity IDs (registry is keyed by unique_id)."""
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    reg.async_get_or_create(
        "sensor", DOMAIN, "butterflymx_last_call_tenant-1",
        suggested_object_id="last_call_unit_101", config_entry=config_entry,
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.last_call_unit_101") is not None
    assert hass.states.get("sensor.unit_101_last_call") is None
