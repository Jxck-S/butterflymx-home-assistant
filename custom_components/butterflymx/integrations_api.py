"""ButterflyMX tenant webhook integrations (REST v4).

Docs: https://apidocs.butterflymx.com/docs/webhooks

These are the only calls in this integration that change the ButterflyMX
account, and they only touch webhook integrations on the resident's own tenant:

- GET    /v4/tenants/{tenant}/integrations        (list)
- POST   /v4/tenants/{tenant}/integrations        (create one call/create webhook)
- DELETE /v4/tenants/{tenant}/integrations/{id}   (remove it again)

They use the same API token as the GraphQL requests.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp
from butterflymx import ButterflyMXApiError, ButterflyMXAuthError, ButterflyMXClient, ButterflyMXConnectionError

from .const import WEBHOOK_SECRET_HEADER

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.butterflymx.com/v4"
TIMEOUT = aiohttp.ClientTimeout(total=15)


def tenant_number(tenant_id: str) -> str:
    """'prod-tenant-9674941' -> '9674941' (the REST API uses the number)."""
    match = re.search(r"(\d+)$", str(tenant_id))
    if not match:
        raise ButterflyMXApiError(f"Can't find a tenant number in {tenant_id!r}")
    return match.group(1)


def call_webhook_payload(url: str, secret: str) -> dict[str, Any]:
    """Body for a tenant integration that POSTs each new call to `url` with the secret header."""
    return {
        "data": {
            "type": "integrations",
            "attributes": {
                "integrator": "webhook",
                "configuration": {"url": url, "method": "post", "headers": {WEBHOOK_SECRET_HEADER: secret}},
                "bindings": [{"resource_type": "call", "actions": ["create"]}],
            },
        }
    }


def _url_of(item: dict[str, Any]) -> str | None:
    # The live list returns flat items with `config`; `attributes.configuration` is a fallback
    attributes = item.get("attributes") or item
    config = attributes.get("config") or attributes.get("configuration") or {}
    return config.get("url") or None


class TenantWebhooks:
    """List, create and delete call webhooks on one account's tenants."""

    def __init__(self, client: ButterflyMXClient, session: aiohttp.ClientSession) -> None:
        self._client = client
        self._session = session

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        await self._client.ensure_token()
        for attempt in range(2):
            token = self._client.access_token
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": self._client.USER_AGENT,
            }
            if payload is not None:
                headers["Content-Type"] = "application/json"
            try:
                async with self._session.request(
                    method, f"{API_BASE}{path}", json=payload, headers=headers, timeout=TIMEOUT
                ) as resp:
                    status, text = resp.status, await resp.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise ButterflyMXConnectionError(f"{method} {path} failed: {err!r}") from err
            if status != 401 or attempt == 1:
                break
            await self._client.ensure_token(invalid_token=token)
        if status in (401, 403):
            raise ButterflyMXAuthError(f"{method} {path}: HTTP {status}")
        if status >= 500:
            raise ButterflyMXConnectionError(f"{method} {path}: HTTP {status}")
        if status >= 400:
            # Never echo the body: a rejected create could repeat our secret header
            raise ButterflyMXApiError(f"{method} {path}: HTTP {status}")
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError as err:
            raise ButterflyMXApiError(f"{method} {path}: response wasn't JSON") from err

    async def list(self, tenant_id: str) -> list[dict[str, Any]]:
        """All webhook integrations on the tenant (first 50 is plenty for a resident)."""
        data = await self._request("GET", f"/tenants/{tenant_number(tenant_id)}/integrations")
        items = (data or {}).get("data") or []
        return [i for i in items if isinstance(i, dict)]

    async def ensure_call_webhook(self, tenant_id: str, url: str, secret: str) -> str:
        """Return the id of the call webhook pointing at `url`, creating it only if none exists."""
        for item in await self.list(tenant_id):
            if _url_of(item) == url and item.get("id") is not None:
                _LOGGER.debug("Reusing ButterflyMX integration %s for tenant %s", item["id"], tenant_id)
                return str(item["id"])
        created = await self._request(
            "POST", f"/tenants/{tenant_number(tenant_id)}/integrations", call_webhook_payload(url, secret)
        )
        integration_id = ((created or {}).get("data") or {}).get("id")
        if integration_id is None:
            raise ButterflyMXApiError("Created a webhook integration but the response had no id")
        _LOGGER.info("Created ButterflyMX call webhook %s for tenant %s", integration_id, tenant_id)
        return str(integration_id)

    async def delete(self, tenant_id: str, integration_id: str) -> None:
        """Delete one integration. Already gone counts as done."""
        try:
            await self._request("DELETE", f"/tenants/{tenant_number(tenant_id)}/integrations/{integration_id}")
        except ButterflyMXApiError as err:
            if "HTTP 404" not in str(err):
                raise
