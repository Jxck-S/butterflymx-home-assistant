"""Instant call alerts: a ButterflyMX tenant webhook delivered through a Nabu Casa cloudhook.

ButterflyMX offers no push feed to a resident app token. What it does offer is
a webhook integration on the tenant (`call` / `create`) that POSTs as soon as
someone buzzes. Home Assistant needs a public HTTPS address for that; this
uses the Home Assistant Cloud cloudhook, so nothing is exposed but one random
webhook URL. Without a logged-in Home Assistant Cloud, nothing here runs and
the 30-second poll stays the only source of new calls.

ButterflyMX doesn't sign deliveries, so the integration is created with a
random secret in a custom header, and every request without it gets a 401.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Any

from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_BMX_INTEGRATIONS,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    CONF_WEBHOOK_URL,
    DOMAIN,
    SIGNAL_WEBHOOK_CALL,
    WEBHOOK_SECRET_HEADER,
    WEBHOOK_TENANT_PARAM,
)
from .coordinator import ButterflyMXConfigEntry, ButterflyMXCoordinator
from .integrations_api import TenantWebhooks, tenant_number

_LOGGER = logging.getLogger(__name__)


def _cloud() -> Any:
    """The cloud component, imported only when it is loaded (it pulls in a lot)."""
    from homeassistant.components import cloud

    return cloud


def cloud_ready(hass: HomeAssistant) -> bool:
    """Home Assistant Cloud is set up with an active subscription (cloudhooks need one)."""
    return "cloud" in hass.config.components and _cloud().async_active_subscription(hass)


def tenant_url(base: str, tenant_id: str) -> str:
    return f"{base}?{WEBHOOK_TENANT_PARAM}={tenant_number(tenant_id)}"


async def async_setup_call_webhook(
    hass: HomeAssistant, entry: ButterflyMXConfigEntry, coordinator: ButterflyMXCoordinator
) -> bool:
    """Register the local webhook and, in the background, the cloudhook and ButterflyMX integration.

    Returns False (polling only) when Home Assistant Cloud isn't available.
    Failures after that are logged and leave polling running.
    """
    if not cloud_ready(hass):
        _LOGGER.info("Home Assistant Cloud isn't logged in; ButterflyMX calls are found by polling only")
        return False

    data = dict(entry.data)
    if not data.get(CONF_WEBHOOK_ID) or not data.get(CONF_WEBHOOK_SECRET):
        data[CONF_WEBHOOK_ID] = data.get(CONF_WEBHOOK_ID) or webhook.async_generate_id()
        data[CONF_WEBHOOK_SECRET] = data.get(CONF_WEBHOOK_SECRET) or secrets.token_urlsafe(32)
        hass.config_entries.async_update_entry(entry, data=data)
    webhook_id = data[CONF_WEBHOOK_ID]

    webhook.async_register(
        hass,
        DOMAIN,
        "ButterflyMX calls",
        webhook_id,
        _make_handler(entry, coordinator),
        allowed_methods=["POST"],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))

    cloud = _cloud()

    async def connect() -> None:
        try:
            await async_link_tenants(hass, entry, coordinator)
        except Exception:  # noqa: BLE001 - never break setup; polling keeps working
            _LOGGER.warning("Couldn't set up the ButterflyMX call webhook; using polling only", exc_info=True)

    if cloud.async_is_connected(hass):
        entry.async_create_background_task(hass, connect(), "butterflymx_call_webhook")
    else:
        # Right after a restart the cloud connects a little later than this entry loads
        @callback
        def on_change(state: Any) -> None:
            if state == cloud.CloudConnectionState.CLOUD_CONNECTED:
                remove()
                entry.async_create_background_task(hass, connect(), "butterflymx_call_webhook")

        remove = cloud.async_listen_connection_change(hass, on_change)
        entry.async_on_unload(lambda: remove())
    return True


async def async_link_tenants(
    hass: HomeAssistant, entry: ButterflyMXConfigEntry, coordinator: ButterflyMXCoordinator
) -> None:
    """Get the cloudhook URL and make sure each tenant has exactly our call webhook."""
    base = await _cloud().async_get_or_create_cloudhook(hass, entry.data[CONF_WEBHOOK_ID])
    api = TenantWebhooks(coordinator.client, async_get_clientsession(hass))
    linked = dict(entry.data.get(CONF_BMX_INTEGRATIONS) or {})
    for tenant in coordinator.tenants:
        linked[tenant.id] = await api.ensure_call_webhook(
            tenant.id, tenant_url(base, tenant.id), entry.data[CONF_WEBHOOK_SECRET]
        )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_WEBHOOK_URL: base, CONF_BMX_INTEGRATIONS: linked}
    )
    _LOGGER.info("ButterflyMX call webhook active for %d tenant(s)", len(linked))


async def async_remove_call_webhook(hass: HomeAssistant, entry: ButterflyMXConfigEntry, client: Any) -> None:
    """Delete the ButterflyMX integrations and the cloudhook. Logs, never raises."""
    linked: dict[str, str] = entry.data.get(CONF_BMX_INTEGRATIONS) or {}
    if linked and client is not None:
        api = TenantWebhooks(client, async_get_clientsession(hass))
        for tenant_id, integration_id in linked.items():
            try:
                await api.delete(tenant_id, integration_id)
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Couldn't delete ButterflyMX webhook integration %s on tenant %s; "
                    "delete it with DELETE /v4/tenants/%s/integrations/%s",
                    integration_id,
                    tenant_id,
                    tenant_number(tenant_id),
                    integration_id,
                    exc_info=True,
                )
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if webhook_id and "cloud" in hass.config.components:
        try:
            await _cloud().async_delete_cloudhook(hass, webhook_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("No cloudhook to delete for %s", webhook_id, exc_info=True)


def extract_call(body: Any) -> dict[str, str | None] | None:
    """Pull call details out of a delivery. Returns None for non-call events.

    Documented envelope: {"event": {"resource_type": "call", "action": "create", "data": {...}}}.
    Older deliveries put the call at the top level or under "call"; those are accepted too.
    """
    if not isinstance(body, dict):
        return None
    event = body["event"] if isinstance(body.get("event"), dict) else body
    if event.get("resource_type") not in (None, "call"):
        return None
    if isinstance(event.get("data"), dict):
        data = event["data"]
    elif isinstance(event.get("call"), dict):
        data = event["call"]
    else:
        data = event
    call_id, guid = data.get("id"), data.get("guid")
    if call_id is None and guid is None:
        return None

    def upper(value: Any) -> str | None:
        return str(value).upper() if value else None

    return {
        "id": str(call_id) if call_id is not None else None,
        "guid": guid,
        "status": upper(data.get("status") or body.get("status")) or "INITIALIZING",
        "type": upper(data.get("notification_type")),
        "device": data.get("panel_name") or data.get("source_name") or data.get("device_name"),
        "logged_at": data.get("logged_at") or data.get("created_at"),
        "image_url": data.get("image_url") or data.get("medium_url") or data.get("thumb_url"),
    }


def _make_handler(entry: ButterflyMXConfigEntry, coordinator: ButterflyMXCoordinator):
    async def handle(hass: HomeAssistant, webhook_id: str, request: Request) -> Response:
        expected = entry.data.get(CONF_WEBHOOK_SECRET) or ""
        given = request.headers.get(WEBHOOK_SECRET_HEADER, "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            _LOGGER.warning("Rejected a ButterflyMX webhook delivery without the right secret")
            return Response(status=401)

        number = request.query.get(WEBHOOK_TENANT_PARAM)
        tenants = coordinator.tenants
        tenant = next((t for t in tenants if number and tenant_number(t.id) == number), None)
        if tenant is None and number is None and len(tenants) == 1:
            tenant = tenants[0]
        if tenant is None:
            return Response(status=404)

        try:
            body = await request.json()
        except ValueError:
            body = None
        call = extract_call(body)
        if call is not None:
            async_dispatcher_send(hass, SIGNAL_WEBHOOK_CALL.format(entry_id=entry.entry_id, tenant_id=tenant.id), call)
        # Fetch full details (image, door name) now rather than at the next poll
        entry.async_create_background_task(hass, coordinator.async_request_refresh(), "butterflymx_refresh")
        return Response(status=200)

    return handle
