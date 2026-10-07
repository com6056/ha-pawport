"""Tests for setup, polling, and re-signing in."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.pawport.api import GRAPHQL_URL
from custom_components.pawport.const import CONF_AUTH_TOKEN, DOMAIN, SCAN_INTERVAL

from .conftest import DOOR_ID, NEW_TOKEN, FakePawport, setup_entry


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, by: timedelta = SCAN_INTERVAL
) -> None:
    freezer.tick(by)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DOOR_ID), config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Dog Door"
    assert device.manufacturer == "Pawport"
    assert device.sw_version == "2.4.1"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_rejected_token_without_password_starts_reauth(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.valid_token = "something-else"
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_rejected_token_with_password_signs_in_again(
    hass: HomeAssistant, pawport: FakePawport, password_entry: MockConfigEntry
) -> None:
    pawport.valid_token = "expired-elsewhere"
    await setup_entry(hass, password_entry)
    assert password_entry.state is ConfigEntryState.LOADED
    assert password_entry.data[CONF_AUTH_TOKEN] == NEW_TOKEN
    assert not hass.config_entries.flow.async_progress()


async def test_stored_password_no_longer_valid(
    hass: HomeAssistant, pawport: FakePawport, password_entry: MockConfigEntry
) -> None:
    pawport.valid_token = "expired-elsewhere"
    pawport.password = "changed"
    await setup_entry(hass, password_entry)
    assert password_entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.config_entries.flow.async_progress()


async def test_transient_failure_then_recovery(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    assert hass.states.get("lock.dog_door").state == "locked"

    pawport.overrides["authDataGet"] = AiohttpClientMockResponse("post", GRAPHQL_URL, status=503)
    await tick(hass, freezer)
    assert hass.states.get("lock.dog_door").state == "unavailable"

    del pawport.overrides["authDataGet"]
    await tick(hass, freezer)
    assert hass.states.get("lock.dog_door").state == "locked"


async def test_setup_retries_when_cloud_down(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.overrides["authDataGet"] = AiohttpClientMockResponse("post", GRAPHQL_URL, status=503)
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_new_door_appears_and_old_one_is_removed(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    second = {**pawport.door_state(), "doorID": "door-2"}
    pawport.context["doors"].append({"doorID": "door-2", "name": "Cat Flap"})
    pawport.context["doorStates"].append(second)
    await tick(hass, freezer)
    assert hass.states.get("lock.cat_flap") is not None

    # A door removed from the account loses its device on the next setup.
    pawport.context["doors"].pop(0)
    pawport.context["doorStates"].pop(0)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    assert devices.async_get_device_by_identifier((DOMAIN, DOOR_ID), config_entry.entry_id) is None
    assert (
        devices.async_get_device_by_identifier((DOMAIN, "door-2"), config_entry.entry_id)
        is not None
    )


async def test_remove_device(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    assert await async_setup_component(hass, "config", {})
    await setup_entry(hass, config_entry)
    devices = dr.async_get(hass)
    live = devices.async_get_device_by_identifier((DOMAIN, DOOR_ID), config_entry.entry_id)
    assert live is not None
    gone = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, "gone")}
    )
    client = await hass_ws_client(hass)

    async def remove(device_id: str) -> bool:
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove_config_entry",
                "config_entry_id": config_entry.entry_id,
                "device_id": device_id,
            }
        )
        response = await client.receive_json()
        return bool(response["success"])

    assert not await remove(live.id)
    assert await remove(gone.id)


async def test_entities_registered(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    entities = er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
    assert sorted(e.unique_id for e in entities) == sorted(
        f"{DOOR_ID}_{key}"
        for key in ("lock", "hold_open", "battery", "charging", "plugged_in", "online")
    )
