"""Config flow for ButterflyMX."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from butterflymx import (
    ButterflyMXAuthError,
    ButterflyMXClient,
    ButterflyMXError,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKENS, DOMAIN

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class ButterflyMXConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ButterflyMX."""

    VERSION = 1

    async def _try_login(self, email: str, password: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Log in. Returns (tokens, errors)."""
        client = ButterflyMXClient(email, password, session=async_get_clientsession(self.hass))
        try:
            await client.login()
        except ButterflyMXAuthError:
            return None, {"base": "invalid_auth"}
        except ButterflyMXError:
            return None, {"base": "cannot_connect"}
        return client.tokens, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            tokens, errors = await self._try_login(email, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD], CONF_TOKENS: tokens},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauth when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, errors = await self._try_login(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD], CONF_TOKENS: tokens},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )
