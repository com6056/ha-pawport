"""Number settings for Pawport doors.

Ranges are the ones the Pawport app's own sliders use.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities
from .models import DoorState

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PawportNumberDescription(NumberEntityDescription):
    """Describes a door number setting and the command that sets it."""

    value_fn: Callable[[DoorState], int | None]
    command: str
    argument: str


def _number(
    key: str, minimum: int, value_fn: Callable[[DoorState], int | None], command: str, argument: str
) -> PawportNumberDescription:
    return PawportNumberDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        native_min_value=minimum,
        native_max_value=5,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=value_fn,
        command=command,
        argument=argument,
    )


NUMBERS: tuple[PawportNumberDescription, ...] = (
    _number("volume", 0, lambda s: s.speaker_volume, "set_volume", "volume"),
    _number("brightness", 0, lambda s: s.led_brightness, "set_brightness", "ledBrightness"),
    # Tag detection distance; the app describes 1 as about a foot and 5 as about five.
    _number("inside_range", 1, lambda s: s.inside_range, "set_inside_range", "range"),
    _number("outside_range", 1, lambda s: s.outside_range, "set_outside_range", "range"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door number settings."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportNumber(coordinator, door_id, d) for d in NUMBERS],
    )


class PawportNumber(PawportDoorEntity, NumberEntity):
    """A door number setting."""

    entity_description: PawportNumberDescription

    @property
    def native_value(self) -> int | None:
        """Return the current setting."""
        state = self.door_state
        return self.entity_description.value_fn(state) if state else None

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        description = self.entity_description
        await self.async_send(description.command, {description.argument: int(value)})
