import pytest
from butterflymx import ButterflyMXAuthError, ButterflyMXConnectionError
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.butterflymx.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKENS, DOMAIN

from .conftest import EMAIL, PASSWORD, TOKENS


async def start_flow(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_user_flow_creates_entry_with_tokens(hass, mock_client):
    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: f" {EMAIL} ", CONF_PASSWORD: PASSWORD}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD, CONF_TOKENS: TOKENS}
    assert result["result"].unique_id == EMAIL
    assert "session" in mock_client.init_kwargs  # uses HA's shared session


@pytest.mark.parametrize(
    ("error", "key"),
    [(ButterflyMXAuthError("bad"), "invalid_auth"), (ButterflyMXConnectionError("down"), "cannot_connect")],
)
async def test_user_flow_errors_then_recovers(hass, mock_client, error, key):
    mock_client.login.side_effect = error
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    mock_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_account_aborts(hass, mock_client, config_entry):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL.upper(), CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password_and_tokens(hass, setup_integration, mock_client):
    entry = setup_integration
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_client.login.side_effect = ButterflyMXAuthError("bad")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "still-wrong"})
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.login.side_effect = None
    mock_client.tokens = {"access_token": "new", "refresh_token": "new", "expires_at": 1}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "new-password"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_TOKENS]["access_token"] == "new"
