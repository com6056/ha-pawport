"""The lights on Pawport doors."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.light import LightEntity, LightEntityDescription
from homeassistant.components.light.const import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ColorMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from . import PawportConfigEntry
from .coordinator import PawportCoordinator
from .entity import PawportDoorEntity, async_add_door_entities

PARALLEL_UPDATES = 1

# The app's brightness slider runs 0 to 5. Home Assistant has no "on but
# dark", so its brightness maps onto 1 to 5 and 0 reads as the dimmest.
BRIGHTNESS_SCALE = (1, 5)

LIGHTS = LightEntityDescription(
    key="lights", translation_key="lights", entity_category=EntityCategory.CONFIG
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door lights."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportLight(coordinator, door_id, LIGHTS)],
    )


def rgb_hex(rgb: tuple[int, int, int]) -> str:
    """Format a color the way the app sends it: six lowercase hex digits, no ``#``."""
    return "".join(f"{max(0, min(int(c), 255)):02x}" for c in rgb)


class PawportLight(PawportDoorEntity, LightEntity):
    """The light bar on a door: on or off, brightness and color."""

    _attr_color_mode = ColorMode.RGB

    def __init__(
        self, coordinator: PawportCoordinator, door_id: str, description: LightEntityDescription
    ) -> None:
        """Initialize for one door."""
        super().__init__(coordinator, door_id, description)
        self._attr_supported_color_modes = {ColorMode.RGB}

    @property
    def is_on(self) -> bool | None:
        """Return whether the lights are enabled."""
        state = self.door_state
        return state.led_enabled if state else None

    @property
    def brightness(self) -> int | None:
        """Return the brightness on Home Assistant's 1 to 255 scale."""
        state = self.door_state
        if state is None or state.led_brightness is None:
            return None
        level = max(BRIGHTNESS_SCALE[0], min(state.led_brightness, BRIGHTNESS_SCALE[1]))
        return value_to_brightness(BRIGHTNESS_SCALE, level)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the color."""
        state = self.door_state
        return state.led_color if state else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lights on, changing brightness or color if asked."""
        commands: list[tuple[str, dict[str, Any]]] = []
        if not self.is_on:
            commands.append(("set_leds_enabled", {"enable": True}))
        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None:
            commands.append(("set_color", {"rgbHex": rgb_hex(rgb)}))
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            level = math.ceil(brightness_to_value(BRIGHTNESS_SCALE, brightness))
            commands.append(("set_brightness", {"ledBrightness": level}))
        if not commands:
            commands.append(("set_leds_enabled", {"enable": True}))
        await self._send_all(commands)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lights off."""
        await self._send_all([("set_leds_enabled", {"enable": False})])

    async def _send_all(self, commands: list[tuple[str, dict[str, Any]]]) -> None:
        """Send the commands in order, then refresh once."""

        async def send() -> None:
            for command, arguments in commands:
                await self.coordinator.client.send_door_command(self.door_id, command, arguments)

        await self.coordinator.async_command(send)
