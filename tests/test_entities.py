"""Tests for the door entities and diagnostics."""

from __future__ import annotations

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN, SERVICE_LOCK, SERVICE_UNLOCK
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.pawport.api import GRAPHQL_URL

from .conftest import EMAIL, TOKEN, FakePawport, setup_entry

LOCK = "lock.dog_door"
HOLD_OPEN = "switch.dog_door_hold_open"


async def call(hass: HomeAssistant, domain: str, service: str, entity_id: str) -> None:
    await hass.services.async_call(domain, service, {ATTR_ENTITY_ID: entity_id}, blocking=True)


async def test_lock(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    assert hass.states.get(LOCK).state == "locked"

    await call(hass, LOCK_DOMAIN, SERVICE_UNLOCK, LOCK)
    assert pawport.commands[-1] == ("door_lock", {"locked": False})
    assert hass.states.get(LOCK).state == "unlocked"

    await call(hass, LOCK_DOMAIN, SERVICE_LOCK, LOCK)
    assert pawport.commands[-1] == ("door_lock", {"locked": True})
    assert hass.states.get(LOCK).state == "locked"


async def test_hold_open(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    assert hass.states.get(HOLD_OPEN).state == "off"

    await call(hass, SWITCH_DOMAIN, SERVICE_TURN_ON, HOLD_OPEN)
    assert pawport.commands[-1] == ("force_open", {"forceOpen": True})
    assert hass.states.get(HOLD_OPEN).state == "on"

    await call(hass, SWITCH_DOMAIN, SERVICE_TURN_OFF, HOLD_OPEN)
    assert hass.states.get(HOLD_OPEN).state == "off"


async def test_sensors(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.door_state().update(
        isCharging=True, isPluggedIn=True, offlineSince="2026-10-06T00:00:00Z"
    )
    await setup_entry(hass, config_entry)
    battery = hass.states.get("sensor.dog_door_battery")
    assert battery.state == "87"
    assert battery.attributes["unit_of_measurement"] == "%"
    assert hass.states.get("binary_sensor.dog_door_charging").state == "on"
    assert hass.states.get("binary_sensor.dog_door_plugged_in").state == "on"
    assert hass.states.get("binary_sensor.dog_door_connectivity").state == "off"


async def test_door_without_state_is_unavailable(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.context["doorStates"] = []
    await setup_entry(hass, config_entry)
    assert hass.states.get(LOCK).state == "unavailable"
    assert hass.states.get("sensor.dog_door_battery").state == "unavailable"


async def test_command_failure(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    pawport.overrides["sendDoorCommand"] = AiohttpClientMockResponse(
        "post", GRAPHQL_URL, json={"data": {"sendDoorCommand": False}}
    )
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await call(hass, LOCK_DOMAIN, SERVICE_UNLOCK, LOCK)
    assert hass.states.get(LOCK).state == "locked"


async def test_command_auth_failure_starts_reauth(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    pawport.valid_token = "revoked"
    with pytest.raises(HomeAssistantError, match="Sign in again"):
        await call(hass, LOCK_DOMAIN, SERVICE_UNLOCK, LOCK)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_diagnostics_redacts(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    await setup_entry(hass, config_entry)
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    text = str(diagnostics)
    assert TOKEN not in text
    assert EMAIL not in text
    assert diagnostics["account"]["doorStates"][0]["batteryChargeLevel"] == 87
