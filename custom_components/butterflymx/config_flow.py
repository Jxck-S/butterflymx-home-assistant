"""Config flow for ButterflyMX."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from butterflymx import (
    ButterflyMXApiError,
    ButterflyMXAuthError,
    ButterflyMXClient,
    ButterflyMXConnectionError,
    ButterflyMXError,
    ButterflyMXInvalidVerificationCode,
    ButterflyMXVerificationRequired,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .auth import get_pending_verification, pop_pending_verification, remember_challenge
from .const import CONF_CODE, CONF_EMAIL, CONF_PASSWORD, CONF_RESEND, CONF_TOKENS, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _six_digit_code(value: Any) -> str | None:
    """Return the 6-digit code from the text, or None if it is not one.

    Validated in the step, not the schema: HA's frontend can only serialize
    plain types, and a custom validator in data_schema crashes the flow.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) != 6 or not value.isdigit():
        return None
    return value


def _verify_schema(can_resend: bool) -> vol.Schema:
    code_key = vol.Optional(CONF_CODE) if can_resend else vol.Required(CONF_CODE)
    # one-time-code lets iOS/Android offer the texted code above the keyboard.
    code_field = TextSelector(TextSelectorConfig(type=TextSelectorType.TEL, autocomplete="one-time-code"))
    fields: dict[Any, Any] = {code_key: code_field}
    if can_resend:
        fields[vol.Optional(CONF_RESEND, default=False)] = bool
    return vol.Schema(fields)


def _code_error(err: ButterflyMXInvalidVerificationCode) -> str:
    if "expired" in str(err).lower():
        return "verification_expired"
    return "invalid_code"


# Handlers return these to the verify step. They are not translation keys.
_SHOW_FORM = "show_form"
_SESSION_EXPIRED = "session_expired"


def _resend_completed_login(client: ButterflyMXClient) -> bool:
    """True when resend followed a redirect all the way to tokens.

    A resend that only refreshes the code form leaves `_pending_login` set.
    Test doubles do not have that attribute until a test sets it; MagicMock
    would otherwise invent a truthy access token and look finished.
    """
    if "_pending_login" not in vars(client):
        return False
    return client._pending_login is None and bool(client.access_token)


class ButterflyMXConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ButterflyMX."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._client: ButterflyMXClient | None = None
        self._pending: ButterflyMXVerificationRequired | ButterflyMXInvalidVerificationCode | None = None
        self._email: str | None = None
        self._password: str | None = None
        self._base_error: str | None = None

    async def _drop_client(self) -> None:
        """Close a login attempt we are finished with. Does not log secrets."""
        client = self._client
        self._client = None
        self._pending = None
        if client is not None:
            await client.close()

    def _set_pending(self, challenge: ButterflyMXVerificationRequired | ButterflyMXInvalidVerificationCode) -> None:
        self._pending = challenge
        if self.source == SOURCE_REAUTH:
            remember_challenge(self.hass, self._get_reauth_entry().entry_id, challenge)

    async def _login(self, email: str, password: str) -> str | None:
        """Log in. Return an error key, ``verify`` when a code is required, or None.

        On success or ``verify``, ``self._client`` holds the session. Tokens are
        read from it only after the login has finished.
        """
        await self._drop_client()
        self._email = email
        self._password = password
        client = ButterflyMXClient(email, password, session=async_get_clientsession(self.hass))
        self._client = client
        try:
            await client.login()
        except ButterflyMXVerificationRequired as err:
            self._set_pending(err)
            return "verify"
        except ButterflyMXAuthError:
            await self._drop_client()
            return "invalid_auth"
        except ButterflyMXError as err:
            _LOGGER.warning("ButterflyMX login failed: %s: %s", type(err).__name__, err)
            await self._drop_client()
            return "cannot_connect"
        self._pending = None
        return None

    async def _finish(self) -> ConfigFlowResult:
        """Create or update the entry from the client that just logged in."""
        if self._client is None or self._email is None or self._password is None:
            return await self._restart_after_expired()
        tokens = dict(self._client.tokens)
        email = self._email
        password = self._password
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            pop_pending_verification(self.hass, entry.entry_id)
            await self._drop_client()
            return self.async_update_reload_and_abort(
                entry,
                data_updates={CONF_PASSWORD: password, CONF_TOKENS: tokens},
            )
        await self._drop_client()
        return self.async_create_entry(
            title=email,
            data={CONF_EMAIL: email, CONF_PASSWORD: password, CONF_TOKENS: tokens},
        )

    async def _restart_after_expired(self) -> ConfigFlowResult:
        """The accounts session is gone. Ask for the password, which texts a new code."""
        if self.source == SOURCE_REAUTH:
            pop_pending_verification(self.hass, self._get_reauth_entry().entry_id)
        await self._drop_client()
        self._base_error = "verification_expired"
        if self.source == SOURCE_REAUTH:
            return await self.async_step_reauth_confirm()
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if self._base_error and user_input is None:
            errors["base"] = self._base_error
            self._base_error = None
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            outcome = await self._login(email, user_input[CONF_PASSWORD])
            if outcome is None:
                return await self._finish()
            if outcome == "verify":
                return await self.async_step_verify()
            errors = {"base": outcome}

        suggested = user_input
        if suggested is None and self._email:
            suggested = {CONF_EMAIL: self._email}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauth. A code already texted at runtime is entered here, not requested again."""
        entry = self._get_reauth_entry()
        pending = get_pending_verification(self.hass, entry.entry_id)
        if pending is not None:
            self._client = pending.client
            self._pending = pending.challenge
            self._email = entry.data[CONF_EMAIL]
            self._password = entry.data[CONF_PASSWORD]
            return await self.async_step_verify()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the password. A correct password may still need the texted code."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if self._base_error and user_input is None:
            errors["base"] = self._base_error
            self._base_error = None
        if user_input is not None:
            outcome = await self._login(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if outcome is None:
                return await self._finish()
            if outcome == "verify":
                return await self.async_step_verify()
            errors = {"base": outcome}

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_verify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the 6-digit code ButterflyMX just texted."""
        if self._pending is None or self._client is None:
            return await self._restart_after_expired()

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_RESEND):
                outcome = await self._resend()
            elif (code := _six_digit_code(user_input.get(CONF_CODE))) is None:
                outcome = "invalid_code"
            else:
                outcome = await self._submit(code)
            if outcome is None:
                return await self._finish()
            if outcome == _SESSION_EXPIRED:
                return await self._restart_after_expired()
            if outcome != _SHOW_FORM:
                errors = {"base": outcome}

        can_resend = bool(self._pending and self._pending.can_resend)
        return self.async_show_form(step_id="verify", data_schema=_verify_schema(can_resend), errors=errors)

    async def _submit(self, code: str) -> str | None:
        """Submit the code. Return an error key, or None when login finished."""
        assert self._pending is not None
        try:
            await self._pending.submit_code(code)
        except ButterflyMXInvalidVerificationCode as err:
            self._set_pending(err)
            return _code_error(err)
        except ButterflyMXVerificationRequired as err:
            self._set_pending(err)
            return "invalid_code"
        except ButterflyMXConnectionError:
            return "cannot_connect"
        except ButterflyMXError as err:
            # Auth and API errors here mean the accounts session was discarded.
            _LOGGER.warning("ButterflyMX code submit failed: %s: %s", type(err).__name__, err)
            return _SESSION_EXPIRED
        return None

    async def _resend(self) -> str | None:
        """Ask for another text.

        Return an error key, ``_SHOW_FORM`` when a new code was requested, or
        None when the resend itself finished the login.
        """
        assert self._pending is not None and self._client is not None
        try:
            await self._pending.resend()
        except ButterflyMXInvalidVerificationCode as err:
            self._set_pending(err)
            return _code_error(err)
        except ButterflyMXVerificationRequired as err:
            self._set_pending(err)
            return "invalid_code"
        except ButterflyMXConnectionError:
            return "cannot_connect"
        except ButterflyMXApiError as err:
            if "does not offer resend" in str(err).lower():
                self._pending.can_resend = False
                return _SHOW_FORM
            return _SESSION_EXPIRED
        except ButterflyMXError as err:
            _LOGGER.warning("ButterflyMX resend failed: %s: %s", type(err).__name__, err)
            return _SESSION_EXPIRED
        if _resend_completed_login(self._client):
            return None
        return _SHOW_FORM
