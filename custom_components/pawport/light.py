"""The lights on Pawport doors."""

from __future__ import annotations

import time
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

# A light change reaches the cloud 2-4 seconds after the command (seen live),
# so the poll right after it still reads the old value. Until the cloud
# catches up, or this long at most, the light shows what was asked for.
SETTLE_SECONDS = 15.0

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
        # What was last asked for, shown until the cloud reports it.
        self._pending: dict[str, Any] = {}
        self._pending_until = 0.0

    def _reported(self) -> dict[str, Any]:
        state = self.door_state
        if state is None:  # pragma: no cover - not read while unavailable
            return {}
        level = state.led_brightness
        if level is not None:
            level = max(BRIGHTNESS_SCALE[0], min(level, BRIGHTNESS_SCALE[1]))
        return {"on": state.led_enabled, "level": level, "rgb": state.led_color}

    def _value(self, key: str) -> Any:
        """Return a reading, preferring a just-sent value the cloud hasn't caught up with."""
        reported = self._reported().get(key)
        if key in self._pending:
            if reported == self._pending[key] or time.monotonic() >= self._pending_until:
                del self._pending[key]
            else:
                return self._pending[key]
        return reported

    @property
    def is_on(self) -> bool | None:
        """Return whether the lights are enabled."""
        on: bool | None = self._value("on")
        return on

    @property
    def brightness(self) -> int | None:
        """Return the brightness on Home Assistant's 1 to 255 scale."""
        level = self._value("level")
        return None if level is None else value_to_brightness(BRIGHTNESS_SCALE, level)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the color."""
        rgb: tuple[int, int, int] | None = self._value("rgb")
        return rgb

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lights on, changing brightness or color if asked."""
        commands: list[tuple[str, dict[str, Any]]] = []
        expected: dict[str, Any] = {"on": True}
        if not self.is_on:
            commands.append(("set_leds_enabled", {"enable": True}))
        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None:
            hex_color = rgb_hex(rgb)
            commands.append(("set_color", {"rgbHex": hex_color}))
            expected["rgb"] = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            # Nearest of the door's five levels, so 50% becomes 60%, not 80%.
            level = max(
                BRIGHTNESS_SCALE[0], round(brightness_to_value(BRIGHTNESS_SCALE, brightness))
            )
            commands.append(("set_brightness", {"ledBrightness": level}))
            expected["level"] = level
        if not commands:
            commands.append(("set_leds_enabled", {"enable": True}))
        await self._send_all(commands, expected)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lights off."""
        await self._send_all([("set_leds_enabled", {"enable": False})], {"on": False})

    async def _send_all(
        self, commands: list[tuple[str, dict[str, Any]]], expected: dict[str, Any]
    ) -> None:
        """Send the commands in order, then refresh once."""

        async def send() -> None:
            for command, arguments in commands:
                await self.coordinator.client.send_door_command(self.door_id, command, arguments)

        previous = self._pending
        self._pending = {**previous, **expected}
        self._pending_until = time.monotonic() + SETTLE_SECONDS
        try:
            await self.coordinator.async_command(send)
        except Exception:
            self._pending = previous
            self.async_write_ha_state()
            raise
