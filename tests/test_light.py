"""Tests for the door lights."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_RGB_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.pawport.api import GRAPHQL_URL
from custom_components.pawport.const import SCAN_INTERVAL
from custom_components.pawport.light import SETTLE_SECONDS, rgb_hex

from .conftest import FakePawport, setup_entry

LIGHT = "light.dog_door_lights"


async def turn_on(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT, **data}, blocking=True
    )


async def test_state(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    state = hass.states.get(LIGHT)
    assert state.state == "on"
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.RGB
    assert state.attributes[ATTR_RGB_COLOR] == (94, 225, 90)
    # Level 4 of 5 (132 on the wire, with the door's +128 flag).
    assert state.attributes[ATTR_BRIGHTNESS] == 204


async def test_turn_off_and_on(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT}, blocking=True
    )
    assert pawport.commands[-1] == ("set_leds_enabled", {"enable": False})
    assert hass.states.get(LIGHT).state == "off"

    await turn_on(hass)
    assert pawport.commands[-1] == ("set_leds_enabled", {"enable": True})
    assert hass.states.get(LIGHT).state == "on"


async def test_turn_on_while_on_resends_enable(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    await turn_on(hass)
    assert pawport.commands == [("set_leds_enabled", {"enable": True})]


@pytest.mark.parametrize(
    ("brightness", "level"),
    # The nearest of the door's five levels (20% steps), never below 1.
    [(255, 5), (204, 4), (153, 3), (128, 3), (102, 2), (77, 2), (52, 1), (1, 1)],
)
async def test_brightness(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    brightness: int,
    level: int,
) -> None:
    await setup_entry(hass, config_entry)
    await turn_on(hass, **{ATTR_BRIGHTNESS: brightness})
    # Already on, so only the brightness is sent.
    assert pawport.commands == [("set_brightness", {"ledBrightness": level})]
    assert pawport.door_state()["ledBrightness"] == level


async def test_brightness_zero_reads_as_dimmest(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.door_state()["ledBrightness"] = 0
    await setup_entry(hass, config_entry)
    assert hass.states.get(LIGHT).attributes[ATTR_BRIGHTNESS] == 51


async def test_color(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    await turn_on(hass, **{ATTR_RGB_COLOR: (255, 10, 171)})
    # Lowercase hex without "#", as the app sends it.
    assert pawport.commands == [("set_color", {"rgbHex": "ff0aab"})]
    assert hass.states.get(LIGHT).attributes[ATTR_RGB_COLOR] == (255, 10, 171)


async def test_turn_on_from_off_with_color_and_brightness(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.door_state()["ledEnabled"] = False
    await setup_entry(hass, config_entry)
    await turn_on(hass, **{ATTR_RGB_COLOR: (0, 0, 255), ATTR_BRIGHTNESS: 255})
    assert pawport.commands == [
        ("set_leds_enabled", {"enable": True}),
        ("set_color", {"rgbHex": "0000ff"}),
        ("set_brightness", {"ledBrightness": 5}),
    ]
    state = hass.states.get(LIGHT)
    assert state.state == "on"
    assert state.attributes[ATTR_BRIGHTNESS] == 255


async def test_missing_readings(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    for key in ("ledEnabled", "ledBrightness", "ledColor"):
        del pawport.door_state()[key]
    await setup_entry(hass, config_entry)
    state = hass.states.get(LIGHT)
    assert state.state == "unknown"


async def test_unavailable_without_door_state(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.context["doorStates"] = []
    await setup_entry(hass, config_entry)
    assert hass.states.get(LIGHT).state == "unavailable"


def test_rgb_hex() -> None:
    assert rgb_hex((94, 225, 90)) == "5ee15a"
    assert rgb_hex((0, 0, 0)) == "000000"
    assert rgb_hex((300, -1, 15)) == "ff000f"


async def test_on_without_brightness_or_color(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    for key in ("ledBrightness", "ledColor"):
        del pawport.door_state()[key]
    await setup_entry(hass, config_entry)
    state = hass.states.get(LIGHT)
    assert state.state == "on"
    assert state.attributes[ATTR_BRIGHTNESS] is None
    assert state.attributes[ATTR_RGB_COLOR] is None


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, by: timedelta) -> None:
    freezer.tick(by)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_shows_the_new_value_while_the_cloud_catches_up(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The poll right after a command still reads the old value, so it isn't shown."""
    await setup_entry(hass, config_entry)
    pawport.lagging = True
    await turn_on(hass, **{ATTR_RGB_COLOR: (255, 0, 0), ATTR_BRIGHTNESS: 255})
    state = hass.states.get(LIGHT)
    assert state.attributes[ATTR_RGB_COLOR] == (255, 0, 0)
    assert state.attributes[ATTR_BRIGHTNESS] == 255

    # The cloud catches up: from then on its readings are shown again.
    pawport.door_state().update(ledColor={"red": 255, "green": 0, "blue": 0}, ledBrightness=5)
    await tick(hass, freezer, SCAN_INTERVAL)
    pawport.door_state().update(ledColor={"red": 0, "green": 0, "blue": 255})
    await tick(hass, freezer, SCAN_INTERVAL)
    assert hass.states.get(LIGHT).attributes[ATTR_RGB_COLOR] == (0, 0, 255)


async def test_gives_up_when_the_cloud_never_catches_up(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    pawport.lagging = True
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT}, blocking=True
    )
    assert hass.states.get(LIGHT).state == "off"
    # The next poll after the settle window shows the cloud's reading again.
    assert timedelta(seconds=SETTLE_SECONDS) < SCAN_INTERVAL
    await tick(hass, freezer, SCAN_INTERVAL)
    assert hass.states.get(LIGHT).state == "on"


async def test_failed_command_shows_the_real_state(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    pawport.overrides["sendDoorCommand"] = AiohttpClientMockResponse(
        "post", GRAPHQL_URL, json={"data": {"sendDoorCommand": False}}
    )
    with pytest.raises(HomeAssistantError):
        await turn_on(hass, **{ATTR_RGB_COLOR: (255, 0, 0)})
    assert hass.states.get(LIGHT).attributes[ATTR_RGB_COLOR] == (94, 225, 90)
