from datetime import timedelta
from unittest.mock import patch

from butterflymx import ButterflyMXConnectionError, Call
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.butterflymx.const import SCAN_INTERVAL, SIGNAL_WEBHOOK_CALL
from custom_components.butterflymx.event import CALL_FRESHNESS, MAX_REMEMBERED_CALLS, SEEN_CALLS

from .conftest import TENANT_ID, make_overview

ENTITY = "event.unit_101_intercom_call"


def _call(call_id: str, status: str = "INITIALIZING", logged_at: str | None = None) -> Call:
    if logged_at is None:
        logged_at = dt_util.utcnow().isoformat()
    return Call(
        {
            "id": call_id,
            "loggedAt": logged_at,
            "displayStatus": status,
            "notificationType": "VISITOR",
            "imageUrl": f"https://img.example/{call_id}",
            "device": {"name": "Main Entrance"},
        }
    )


def _record_call_ids(hass) -> list[str]:
    fired: list[str] = []

    @callback
    def record(event) -> None:
        if event.data["entity_id"] == ENTITY:
            fired.append(event.data["new_state"].attributes.get("call_id"))

    hass.bus.async_listen("state_changed", record)
    return fired


async def _poll(hass, mock_client, calls):
    original = mock_client.tenant.get_overview.side_effect

    def with_calls():
        overview = original()
        overview.calls = calls
        return overview

    mock_client.tenant.get_overview.side_effect = with_calls
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    mock_client.tenant.get_overview.side_effect = original


async def test_calls_at_startup_do_not_fire(hass, setup_integration):
    state = hass.states.get(ENTITY)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["device_class"] == "doorbell"
    assert state.attributes["event_types"] == ["ring"]


async def test_new_call_fires_ring_with_details(hass, setup_integration, mock_client):
    call = _call("c-2")
    await _poll(hass, mock_client, [call, *mock_client.tenant.get_overview.side_effect().calls])

    state = hass.states.get(ENTITY)
    assert state.state != STATE_UNKNOWN
    assert state.attributes["event_type"] == "ring"
    assert state.attributes["call_id"] == "c-2"
    assert state.attributes["status"] == "INITIALIZING"
    assert state.attributes["device"] == "Main Entrance"
    assert state.attributes["type"] == "VISITOR"
    assert state.attributes["logged_at"] == call.logged_at
    assert state.attributes["image_url"] == "https://img.example/c-2"


async def test_same_call_does_not_fire_twice(hass, setup_integration, mock_client):
    events = _record_call_ids(hass)
    await _poll(hass, mock_client, [_call("c-2")])
    # The same call later changes status; that is not a new ring
    await _poll(hass, mock_client, [_call("c-2", status="OPENED_DOOR")])
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_two_calls_between_polls_fire_two_events_oldest_first(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    await _poll(hass, mock_client, [_call("c-4"), _call("c-3")])
    assert fired == ["c-3", "c-4"]


async def test_backlog_is_capped(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    await _poll(hass, mock_client, [_call(f"n-{i}") for i in range(9, 0, -1)])
    assert fired == ["n-5", "n-6", "n-7", "n-8", "n-9"]


async def test_failed_poll_does_not_fire(hass, setup_integration, mock_client):
    mock_client.tenant.get_overview.side_effect = ButterflyMXConnectionError("down")
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    # No ring yet, and a missed poll must not flip the event to unavailable.
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN
    assert hass.states.get("sensor.unit_101_last_call").state == STATE_UNAVAILABLE


def _age(delta: timedelta) -> str:
    return (dt_util.utcnow() - delta).isoformat()


def _send(hass, entry, call: dict) -> None:
    async_dispatcher_send(hass, SIGNAL_WEBHOOK_CALL.format(entry_id=entry.entry_id, tenant_id=TENANT_ID), call)


def _changes(hass) -> list[tuple]:
    """State changes of the intercom event after this is called."""
    found: list[tuple] = []

    @callback
    def record(event) -> None:
        if event.data["entity_id"] != ENTITY:
            return
        new = event.data["new_state"]
        found.append(
            (
                None if new is None else new.state,
                None if new is None else new.attributes.get("event_type"),
                None if new is None else new.attributes.get("call_id"),
                None if new is None else new.attributes.get("status"),
            )
        )

    hass.bus.async_listen("state_changed", record)
    return found


async def test_poll_outage_does_not_replay_the_last_ring(hass, setup_integration, mock_client):
    """Nov 19: coordinator blip must not turn yesterday's ring into a new one.

    A state trigger with no from/to filter is what fired the false push.
    """
    call = _call("prod-call-277497395")
    await _poll(hass, mock_client, [call])
    ring = hass.states.get(ENTITY)
    assert ring.attributes["call_id"] == "prod-call-277497395"
    assert ring.attributes["status"] == "INITIALIZING"
    rung_at = ring.state

    buzzes: list[str] = []

    @callback
    def record(_event) -> None:
        buzzes.append("buzz")

    hass.bus.async_listen("test_buzz", record)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": "someone is buzzing",
                "triggers": [{"trigger": "state", "entity_id": ENTITY}],
                "actions": [{"event": "test_buzz"}],
            }
        },
    )
    await hass.async_block_till_done()

    changes = _changes(hass)
    healthy = mock_client.tenant.get_overview.side_effect
    mock_client.tenant.get_overview.side_effect = ButterflyMXConnectionError("Network unreachable")
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()

    during = hass.states.get(ENTITY)
    assert during.state == rung_at
    assert during.attributes["call_id"] == "prod-call-277497395"
    assert hass.states.get("sensor.unit_101_last_call").state == STATE_UNAVAILABLE

    mock_client.tenant.get_overview.side_effect = healthy
    await _poll(hass, mock_client, [_call("prod-call-277497395", status="OPENED_DOOR", logged_at=call.logged_at)])
    after = hass.states.get(ENTITY)
    assert after.state == rung_at
    assert after.attributes["status"] == "INITIALIZING"
    assert after.attributes["call_id"] == "prod-call-277497395"
    assert changes == []
    assert buzzes == []
    # The sensor still follows the poll, including the status update.
    assert hass.states.get("sensor.unit_101_last_call").state == "Main Entrance - OPENED_DOOR"


async def test_webhook_during_poll_outage_still_rings(hass, setup_integration, mock_client):
    mock_client.tenant.get_overview.side_effect = ButterflyMXConnectionError("Network unreachable")
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.unit_101_last_call").state == STATE_UNAVAILABLE

    fired = _record_call_ids(hass)
    _send(
        hass,
        setup_integration,
        {"id": "277500001", "logged_at": dt_util.utcnow().isoformat(), "status": "INITIALIZING"},
    )
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    assert state.attributes["event_type"] == "ring"
    assert state.attributes["call_id"] == "prod-call-277500001"
    assert fired == ["prod-call-277500001"]
    assert hass.states.get("sensor.unit_101_last_call").state == STATE_UNAVAILABLE


async def test_stale_call_does_not_ring_and_is_remembered(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    old = _age(CALL_FRESHNESS + timedelta(minutes=1))
    await _poll(hass, mock_client, [_call("stale-9", logged_at=old)])
    assert fired == []
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN

    # A later delivery with no timestamp would look live if we had not remembered it.
    _send(hass, setup_integration, {"id": "stale-9"})
    await hass.async_block_till_done()
    assert fired == []


async def test_historical_startup_call_is_not_announced_later(hass, setup_integration):
    """The call already in the first poll (months old in the fixture) never rings."""
    fired = _record_call_ids(hass)
    _send(hass, setup_integration, {"id": "c-1"})
    await hass.async_block_till_done()
    assert fired == []
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN


async def test_two_fresh_calls_already_loaded_both_ring(hass, config_entry, mock_client):
    """The first poll can hold more than one new call. Each must be its own ring.

    Deciding before the entity is added drops every state write but the last.
    """

    def overview():
        data = make_overview(mock_client)
        data.calls = [_call("b"), _call("a"), *data.calls]
        return data

    mock_client.tenant.get_overview.side_effect = overview
    fired = _record_call_ids(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert [call_id for call_id in fired if call_id] == ["a", "b"]


async def test_no_calls_stay_unknown(hass, config_entry, mock_client):
    def empty():
        overview = make_overview(mock_client)
        overview.calls = []
        return overview

    mock_client.tenant.get_overview.side_effect = empty
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == STATE_UNKNOWN
    assert "call_id" not in state.attributes


async def test_fresh_call_just_inside_the_window_rings(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    await _poll(hass, mock_client, [_call("edge-new", logged_at=_age(CALL_FRESHNESS - timedelta(seconds=5)))])
    assert fired == ["edge-new"]


async def test_call_just_outside_the_window_does_not_ring(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    await _poll(hass, mock_client, [_call("edge-old", logged_at=_age(CALL_FRESHNESS + timedelta(seconds=5)))])
    assert fired == []


async def test_clock_skew_ahead_still_rings(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    ahead = (dt_util.utcnow() + timedelta(minutes=2)).isoformat()
    way_ahead = (dt_util.utcnow() + timedelta(hours=2)).isoformat()
    await _poll(hass, mock_client, [_call("skew-ok", logged_at=ahead)])
    await _poll(
        hass,
        mock_client,
        [_call("skew-far", logged_at=way_ahead), _call("skew-ok", logged_at=ahead)],
    )
    assert fired == ["skew-ok"]


async def test_older_fresh_call_after_a_newer_one_still_rings(hass, setup_integration, mock_client):
    """Out of order: a call logged before the last ring is still a ring if it is new and fresh."""
    fired = _record_call_ids(hass)
    newer = _age(timedelta(seconds=5))
    older = _age(timedelta(seconds=30))
    await _poll(hass, mock_client, [_call("newer", logged_at=newer)])
    await _poll(
        hass,
        mock_client,
        [_call("newer", logged_at=newer, status="OPENED_DOOR"), _call("older", logged_at=older)],
    )
    assert fired == ["newer", "older"]
    assert hass.states.get(ENTITY).attributes["call_id"] == "older"
    assert hass.states.get(ENTITY).attributes["status"] == "INITIALIZING"


async def test_status_update_does_not_change_the_event(hass, setup_integration, mock_client):
    call = _call("c-2")
    await _poll(hass, mock_client, [call])
    rung_at = hass.states.get(ENTITY).state
    changes = _changes(hass)
    await _poll(hass, mock_client, [_call("c-2", status="OPENED_DOOR", logged_at=call.logged_at)])
    state = hass.states.get(ENTITY)
    assert state.state == rung_at
    assert state.attributes["status"] == "INITIALIZING"
    assert changes == []
    assert hass.states.get("sensor.unit_101_last_call").state == "Main Entrance - OPENED_DOOR"


async def test_poll_without_timestamp_does_not_ring(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    call = _call("no-time")
    call.logged_at = None
    await _poll(hass, mock_client, [call])
    assert fired == []


async def test_webhook_without_timestamp_rings_once(hass, setup_integration):
    fired = _record_call_ids(hass)
    _send(hass, setup_integration, {"id": "42", "device": "Side Door"})
    _send(hass, setup_integration, {"id": "42", "status": "OPENED_DOOR"})
    await hass.async_block_till_done()
    assert fired == ["prod-call-42"]
    assert hass.states.get(ENTITY).attributes["device"] == "Side Door"
    assert hass.states.get(ENTITY).attributes["status"] is None


async def test_webhook_without_id_lets_the_poll_ring(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    _send(hass, setup_integration, {"device": "Side Door"})
    await hass.async_block_till_done()
    assert fired == []
    await _poll(hass, mock_client, [_call("from-poll")])
    assert fired == ["from-poll"]


async def test_webhook_then_poll_and_poll_then_webhook_ring_once(hass, setup_integration, mock_client):
    fired = _record_call_ids(hass)
    logged = dt_util.utcnow().isoformat()
    _send(hass, setup_integration, {"id": "555", "logged_at": logged, "status": "INITIALIZING"})
    await hass.async_block_till_done()
    await _poll(hass, mock_client, [_call("prod-call-555", status="OPENED_DOOR", logged_at=logged)])
    assert fired == ["prod-call-555"]

    await _poll(hass, mock_client, [_call("second", logged_at=logged)])
    _send(hass, setup_integration, {"id": "second", "logged_at": logged})
    await hass.async_block_till_done()
    assert fired == ["prod-call-555", "second"]


async def test_duplicate_and_out_of_order_webhooks(hass, setup_integration):
    fired = _record_call_ids(hass)
    older = _age(timedelta(seconds=20))
    newer = _age(timedelta(seconds=5))
    _send(hass, setup_integration, {"id": "900", "logged_at": newer})
    _send(hass, setup_integration, {"id": "900", "logged_at": newer, "status": "OPENED_DOOR"})
    _send(hass, setup_integration, {"id": "899", "logged_at": older})
    await hass.async_block_till_done()
    assert fired == ["prod-call-900", "prod-call-899"]


async def test_stale_webhook_does_not_ring(hass, setup_integration):
    fired = _record_call_ids(hass)
    _send(hass, setup_integration, {"id": "12", "logged_at": _age(timedelta(hours=5))})
    await hass.async_block_till_done()
    assert fired == []


async def test_reload_and_restart_do_not_ring_again(hass, setup_integration, mock_client):
    call = _call("prod-call-277497395")
    await _poll(hass, mock_client, [call])
    rung_at = hass.states.get(ENTITY).state
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    await _poll(hass, mock_client, [_call("prod-call-277497395", status="OPENED_DOOR", logged_at=call.logged_at)])
    assert hass.states.get(ENTITY).state == rung_at
    assert hass.states.get(ENTITY).attributes["status"] == "INITIALIZING"

    # Drop the in-memory copy, as a process restart would, and read the file.
    hass.data[SEEN_CALLS].pop(setup_integration.entry_id)
    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    await _poll(hass, mock_client, [_call("prod-call-277497395", logged_at=call.logged_at)])
    state = hass.states.get(ENTITY)
    assert state.state == rung_at
    assert state.attributes["call_id"] == "prod-call-277497395"
    assert state.attributes["status"] == "INITIALIZING"


async def test_upgrade_remembers_the_restored_ring(hass, config_entry, mock_client):
    """2.4.0 stored the last ring on the entity and not in the seen-call file."""
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import mock_restore_cache_with_extra_data

    logged = dt_util.utcnow().isoformat()

    def overview():
        data = make_overview(mock_client)
        data.calls = [_call("prod-call-277497395", logged_at=logged), *data.calls]
        return data

    mock_client.tenant.get_overview.side_effect = overview
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(
                    ENTITY,
                    "2026-11-18T23:43:39.466+00:00",
                    {"event_type": "ring", "call_id": "prod-call-277497395", "status": "INITIALIZING"},
                ),
                {
                    "last_event_type": "ring",
                    "last_event_attributes": {
                        "call_id": "prod-call-277497395",
                        "status": "INITIALIZING",
                    },
                },
            )
        ],
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    # Restoring the old ring is not a new one: the timestamp stays the one from 2.4.0.
    state = hass.states.get(ENTITY)
    assert state.state == "2026-11-18T23:43:39.466+00:00"
    assert state.attributes["call_id"] == "prod-call-277497395"
    fired = _record_call_ids(hass)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert fired == []
    assert hass.states.get(ENTITY).state == "2026-11-18T23:43:39.466+00:00"


async def test_remembered_calls_drop_the_oldest(hass, setup_integration, mock_client):
    with patch("custom_components.butterflymx.event.MAX_REMEMBERED_CALLS", 3):
        # Newest first. Remembered oldest-first, so the cap keeps c, b, a.
        await _poll(
            hass,
            mock_client,
            [_call("a"), _call("b"), _call("c"), _call("d")],
        )
        await hass.async_block_till_done()
    store = hass.data[SEEN_CALLS][setup_integration.entry_id]
    assert store.seen(TENANT_ID, "a")
    assert store.seen(TENANT_ID, "b")
    assert store.seen(TENANT_ID, "c")
    assert not store.seen(TENANT_ID, "d")
    assert MAX_REMEMBERED_CALLS == 200


async def test_removing_the_entry_deletes_remembered_calls(hass, setup_integration, mock_client, hass_storage):
    await _poll(hass, mock_client, [_call("gone")])
    await hass.async_block_till_done()
    key = f"{SEEN_CALLS}.{setup_integration.entry_id}"
    assert key in hass_storage
    assert "gone" in hass_storage[key]["data"]["calls"][TENANT_ID]

    assert await hass.config_entries.async_remove(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
    assert setup_integration.entry_id not in hass.data.get(SEEN_CALLS, {})
