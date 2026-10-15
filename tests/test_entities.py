"""Tests for the door entities and diagnostics."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN, SERVICE_LOCK, SERVICE_UNLOCK
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.pawport.api import GRAPHQL_URL
from custom_components.pawport.const import SCAN_INTERVAL

from .conftest import DOOR_ID, EMAIL, TOKEN, FakePawport, setup_entry

LOCK = "lock.dog_door"
HOLD_OPEN = "switch.dog_door_hold_open"
BATTERY = "sensor.dog_door_battery"
CHARGING = "binary_sensor.dog_door_charging"
PLUGGED_IN = "binary_sensor.dog_door_plugged_in"
INSIDE_SENSOR = "binary_sensor.dog_door_inside_sensor"
OUTSIDE_SENSOR = "binary_sensor.dog_door_outside_sensor"


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


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
    # The isPluggedIn and isCharging fields are ignored, as in the app.
    pawport.door_state().update(
        chargerDetails=2,
        isPluggedIn=False,
        isCharging=False,
        offlineSince="2026-10-06T00:00:00Z",
    )
    await setup_entry(hass, config_entry)
    battery = hass.states.get(BATTERY)
    assert battery.state == "87"
    assert battery.attributes["unit_of_measurement"] == "%"
    assert hass.states.get(CHARGING).state == "on"
    assert hass.states.get(PLUGGED_IN).state == "on"
    assert hass.states.get("binary_sensor.dog_door_connectivity").state == "off"


@pytest.mark.parametrize(
    ("charger", "battery", "charging", "plugged_in"),
    [
        # No battery fitted: the door reads 0%, which would be misleading.
        (0, "unavailable", "unavailable", "on"),
        (1, "87", "off", "on"),
        (2, "87", "on", "on"),
        (3, "87", "off", "off"),
        # A value the app doesn't know.
        (9, "unavailable", "unavailable", "unknown"),
        (None, "unavailable", "unavailable", "unknown"),
    ],
)
async def test_power(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    charger: int | None,
    battery: str,
    charging: str,
    plugged_in: str,
) -> None:
    pawport.door_state()["chargerDetails"] = charger
    await setup_entry(hass, config_entry)
    assert hass.states.get(BATTERY).state == battery
    assert hass.states.get(CHARGING).state == charging
    assert hass.states.get(PLUGGED_IN).state == plugged_in


async def test_battery_fitted_later(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The battery entities come alive without a restart once a battery is fitted."""
    pawport.door_state().update(chargerDetails=0, batteryChargeLevel=0)
    await setup_entry(hass, config_entry)
    assert hass.states.get(BATTERY).state == "unavailable"

    pawport.door_state().update(chargerDetails=2, batteryChargeLevel=40)
    await tick(hass, freezer)
    assert hass.states.get(BATTERY).state == "40"
    assert hass.states.get(CHARGING).state == "on"


async def test_sensor_modules(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    assert hass.states.get(INSIDE_SENSOR).state == "on"
    assert hass.states.get(OUTSIDE_SENSOR).state == "off"
    registry = er.async_get(hass)
    entry = registry.async_get(INSIDE_SENSOR)
    assert entry is not None
    assert entry.entity_category is EntityCategory.DIAGNOSTIC

    # A sensor module added later appears, and one deleted is removed.
    sensors = pawport.context["doors"][0]["sensors"]
    sensors[:] = [
        {"sensorType": 2, "isConnected": True},
        {"sensorType": 4, "isConnected": True},
        # Types the app doesn't name are left out.
        {"sensorType": 9, "isConnected": True},
        {"isConnected": True},
    ]
    await tick(hass, freezer)
    assert registry.async_get(INSIDE_SENSOR) is None
    assert hass.states.get(OUTSIDE_SENSOR).state == "on"
    assert hass.states.get("binary_sensor.dog_door_external_sensor").state == "on"
    sensor_entities = {
        e.unique_id
        for e in er.async_entries_for_config_entry(registry, config_entry.entry_id)
        if e.unique_id.endswith("_sensor")
    }
    assert sensor_entities == {f"{DOOR_ID}_outside_sensor", f"{DOOR_ID}_external_sensor"}


async def test_door_without_state_is_unavailable(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.context["doorStates"] = []
    await setup_entry(hass, config_entry)
    assert hass.states.get(LOCK).state == "unavailable"
    assert hass.states.get(BATTERY).state == "unavailable"
    assert hass.states.get(CHARGING).state == "unavailable"


async def test_command_failure(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    pawport.overrides["sendDoorCommand"] = AiohttpClientMockResponse(
        "post", GRAPHQL_URL, json={"data": {"sendDoorCommand": False}}
    )
    with pytest.raises(HomeAssistantError, match="didn't accept"):
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
