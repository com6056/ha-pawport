"""Tests for the lock and light schedule switches."""

from __future__ import annotations

import copy

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.pawport.api import GRAPHQL_URL
from custom_components.pawport.const import SCAN_INTERVAL
from custom_components.pawport.models import LockSchedule

from .conftest import DOOR_ID, LOCK_SCHEDULE, SCHEDULE_ID, FakePawport, setup_entry

NIGHT = "switch.dog_door_schedule_night"
LIGHTS = "switch.dog_door_light_schedule"


async def call(hass: HomeAssistant, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_lock_schedule(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    state = hass.states.get(NIGHT)
    assert state.state == "on"
    assert state.attributes["start"] == "21:00"
    assert state.attributes["end"] == "06:00"
    assert state.attributes["days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert state.attributes["permission"] == "in_only"

    await call(hass, SERVICE_TURN_OFF, NIGHT)
    assert pawport.commands[-1] == (
        "doorLockScheduleEnabledSet",
        {"doorLockScheduleID": SCHEDULE_ID, "enabled": False},
    )
    assert hass.states.get(NIGHT).state == "off"


async def test_light_schedule(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    state = hass.states.get(LIGHTS)
    assert state.state == "off"
    assert state.attributes["days"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    await call(hass, SERVICE_TURN_ON, LIGHTS)
    assert pawport.commands[-1] == (
        "doorLightScheduleEnabledSet",
        {"doorID": DOOR_ID, "enabled": True},
    )
    assert hass.states.get(LIGHTS).state == "on"

    await call(hass, SERVICE_TURN_OFF, LIGHTS)
    assert hass.states.get(LIGHTS).state == "off"


async def test_schedule_change_rejected(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    for operation, entity_id in (
        ("doorLockScheduleEnabledSet", NIGHT),
        ("doorLightScheduleEnabledSet", LIGHTS),
    ):
        pawport.overrides[operation] = AiohttpClientMockResponse(
            "post", GRAPHQL_URL, json={"data": {operation: False}}
        )
        with pytest.raises(HomeAssistantError, match="rejected"):
            await call(hass, SERVICE_TURN_ON, entity_id)


async def test_schedules_come_and_go(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A deleted schedule's switch leaves the registry; a new one appears."""
    await setup_entry(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get(NIGHT) is not None

    pawport.context["doorLockSchedules"] = [
        {**copy.deepcopy(LOCK_SCHEDULE), "doorLockScheduleID": "sched-2", "name": "Morning"}
    ]
    pawport.context["doorLightSchedules"] = []
    await tick(hass, freezer)
    assert registry.async_get(NIGHT) is None
    assert hass.states.get(NIGHT) is None
    assert registry.async_get(LIGHTS) is None
    assert hass.states.get("switch.dog_door_schedule_morning").state == "on"

    # The same schedule coming back is added again rather than ignored.
    pawport.context["doorLockSchedules"].append(copy.deepcopy(LOCK_SCHEDULE))
    await tick(hass, freezer)
    assert hass.states.get(NIGHT).state == "on"


async def test_schedule_switches_unavailable_when_poll_fails(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    pawport.overrides["authDataGet"] = AiohttpClientMockResponse("post", GRAPHQL_URL, status=503)
    await tick(hass, freezer)
    assert hass.states.get(NIGHT).state == "unavailable"
    assert hass.states.get(LIGHTS).state == "unavailable"
    # A failed poll keeps the last data, so the switches are not removed.
    assert er.async_get(hass).async_get(NIGHT) is not None


def test_lock_schedule_model_edge_cases() -> None:
    schedule = LockSchedule.from_api({"doorLockScheduleID": 5, "days": "junk"})
    assert schedule.schedule_id == "5"
    assert schedule.name == "Schedule"
    assert schedule.days == ()
    assert schedule.permission is None
    assert schedule.enabled is None
