"""Tests for the door settings: switches, numbers, selects, and firmware."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakePawport, setup_entry


@pytest.mark.parametrize(
    ("entity_id", "before", "service", "command", "arguments", "after"),
    [
        (
            "switch.dog_door_sound",
            "on",
            SERVICE_TURN_OFF,
            "set_sound_enabled",
            {"enable": False},
            "off",
        ),
        (
            "switch.dog_door_lights",
            "on",
            SERVICE_TURN_OFF,
            "set_leds_enabled",
            {"enable": False},
            "off",
        ),
        (
            "switch.dog_door_rain_lock",
            "on",
            SERVICE_TURN_OFF,
            "set_rain_lock_enabled",
            {"enable": False},
            "off",
        ),
        (
            "switch.dog_door_lightning_lock",
            "off",
            SERVICE_TURN_ON,
            "set_lightning_lock_enabled",
            {"enable": True},
            "on",
        ),
        # Panel buttons is the inverse of the door's control-panel lockout.
        (
            "switch.dog_door_panel_buttons",
            "on",
            SERVICE_TURN_OFF,
            "set_control_panel_lockout",
            {"enable": True},
            "off",
        ),
    ],
)
async def test_setting_switches(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    entity_id: str,
    before: str,
    service: str,
    command: str,
    arguments: dict[str, Any],
    after: str,
) -> None:
    await setup_entry(hass, config_entry)
    assert hass.states.get(entity_id).state == before
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert pawport.commands[-1] == (command, arguments)
    assert hass.states.get(entity_id).state == after


@pytest.mark.parametrize(
    ("entity_id", "before", "value", "command", "arguments"),
    [
        ("number.dog_door_volume", "3", 5, "set_volume", {"volume": 5}),
        # 132 on the wire is level 4 with the door's +128 flag.
        ("number.dog_door_light_brightness", "4", 2, "set_brightness", {"ledBrightness": 2}),
        ("number.dog_door_inside_tag_range", "2", 4, "set_inside_range", {"range": 4}),
        ("number.dog_door_outside_tag_range", "3", 1, "set_outside_range", {"range": 1}),
    ],
)
async def test_numbers(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    entity_id: str,
    before: str,
    value: int,
    command: str,
    arguments: dict[str, Any],
) -> None:
    await setup_entry(hass, config_entry)
    state = hass.states.get(entity_id)
    assert state.state == before
    assert state.attributes["max"] == 5
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )
    assert pawport.commands[-1] == (command, arguments)
    assert hass.states.get(entity_id).state == str(value)


@pytest.mark.parametrize(
    ("entity_id", "before", "option", "command", "arguments"),
    [
        ("select.dog_door_time_to_close", "10", "30", "set_open_time", {"durationSeconds": 30}),
        ("select.dog_door_open_angle", "90", "120", "set_left_angle", {"angle": 120}),
    ],
)
async def test_selects(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    entity_id: str,
    before: str,
    option: str,
    command: str,
    arguments: dict[str, Any],
) -> None:
    await setup_entry(hass, config_entry)
    assert hass.states.get(entity_id).state == before
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )
    assert pawport.commands[-1] == (command, arguments)
    assert hass.states.get(entity_id).state == option


async def test_select_with_unexpected_value(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    """A value the app never offers reads as unknown rather than a wrong option."""
    pawport.door_state()["openTime"] = 7
    await setup_entry(hass, config_entry)
    assert hass.states.get("select.dog_door_time_to_close").state == "unknown"


async def test_weather_lock_sensors(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.door_state().update(rainLockActive=True)
    await setup_entry(hass, config_entry)
    assert hass.states.get("binary_sensor.dog_door_rain_lock_active").state == "on"
    assert hass.states.get("binary_sensor.dog_door_lightning_lock_active").state == "off"


async def test_firmware(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    state = hass.states.get("update.dog_door_firmware")
    assert state.state == "off"
    assert state.attributes["installed_version"] == "2.4.1"
    # Read-only: installing is left to the Pawport app.
    assert state.attributes["supported_features"] == 0


async def test_firmware_update_available(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.door_state()["latestAvailableFirmwareVersion"] = "2.5.0"
    await setup_entry(hass, config_entry)
    state = hass.states.get("update.dog_door_firmware")
    assert state.state == "on"
    assert state.attributes["latest_version"] == "2.5.0"


async def test_firmware_without_latest_version(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.door_state()["latestAvailableFirmwareVersion"] = None
    await setup_entry(hass, config_entry)
    assert hass.states.get("update.dog_door_firmware").state == "off"


async def test_settings_are_config_entities(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    registry = er.async_get(hass)
    for entity_id in (
        "switch.dog_door_sound",
        "number.dog_door_volume",
        "select.dog_door_time_to_close",
    ):
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.entity_category is EntityCategory.CONFIG
    hold_open = registry.async_get("switch.dog_door_hold_open")
    assert hold_open is not None
    assert hold_open.entity_category is None


async def test_settings_unavailable_without_door_state(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.context["doorStates"] = []
    await setup_entry(hass, config_entry)
    for entity_id in (
        "switch.dog_door_sound",
        "number.dog_door_volume",
        "select.dog_door_open_angle",
        "update.dog_door_firmware",
    ):
        assert hass.states.get(entity_id).state == "unavailable"
