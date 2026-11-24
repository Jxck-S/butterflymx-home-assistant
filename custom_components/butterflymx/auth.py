"""A ButterflyMX login that is waiting on a texted code.

Runtime requests pass the stored tokens into the client. The client uses a
valid access token, then the refresh token, and only then the password.
That password step can text a verification code and raise
`ButterflyMXVerificationRequired` while keeping the accounts session open.
Another request on the same client raises the same challenge and does not
text again, but a new client would. Hold the client that raised it and do
not retry setup or polling until the code is submitted.
"""

from __future__ import annotations

from dataclasses import dataclass

from butterflymx import ButterflyMXClient, ButterflyMXInvalidVerificationCode, ButterflyMXVerificationRequired
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

DATA_PENDING_VERIFICATION = "pending_verification"
VERIFICATION_MESSAGE = "ButterflyMX verification required"
VERIFICATION_EXCEPTIONS = (ButterflyMXVerificationRequired, ButterflyMXInvalidVerificationCode)


@dataclass
class PendingVerification:
    """The client whose accounts session is waiting, and the latest challenge."""

    client: ButterflyMXClient
    challenge: ButterflyMXVerificationRequired | ButterflyMXInvalidVerificationCode


def _store(hass: HomeAssistant) -> dict[str, PendingVerification]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(DATA_PENDING_VERIFICATION, {})


def stash_pending_verification(
    hass: HomeAssistant,
    entry_id: str,
    client: ButterflyMXClient,
    challenge: ButterflyMXVerificationRequired | ButterflyMXInvalidVerificationCode,
) -> None:
    """Remember the open login so reauth can submit the code on it."""
    _store(hass)[entry_id] = PendingVerification(client, challenge)


def get_pending_verification(hass: HomeAssistant, entry_id: str) -> PendingVerification | None:
    """The open login for this entry, if a code was requested and not finished."""
    return hass.data.get(DOMAIN, {}).get(DATA_PENDING_VERIFICATION, {}).get(entry_id)


def pop_pending_verification(hass: HomeAssistant, entry_id: str) -> PendingVerification | None:
    """Drop the open login once the code is accepted or the session is abandoned."""
    store: dict[str, PendingVerification] = hass.data.get(DOMAIN, {}).get(DATA_PENDING_VERIFICATION, {})
    return store.pop(entry_id, None)


def remember_challenge(
    hass: HomeAssistant,
    entry_id: str,
    challenge: ButterflyMXVerificationRequired | ButterflyMXInvalidVerificationCode,
) -> None:
    """Keep the stashed challenge in sync when a new code error replaces it."""
    pending = get_pending_verification(hass, entry_id)
    if pending is not None:
        pending.challenge = challenge


def reauth_flow_active(hass: HomeAssistant, entry_id: str) -> bool:
    """True when this entry already has a reauth flow asking for the code or password."""
    return any(
        flow["context"].get("source") == SOURCE_REAUTH and flow["context"].get("entry_id") == entry_id
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    )


def ensure_reauth_flow(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start reauth if this entry does not already have one.

    A second request is ignored while that flow is open, so the code form stays put.
    """
    if not reauth_flow_active(hass, entry.entry_id):
        entry.async_start_reauth(hass)
