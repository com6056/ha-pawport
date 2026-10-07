"""Select settings for Pawport doors.

Options are the ones the Pawport app offers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities
from .models import DoorState

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PawportSelectDescription(SelectEntityDescription):
    """Describes a door select setting backed by an integer value."""

    value_fn: Callable[[DoorState], int | None]
    command: str
    argument: str


SELECTS: tuple[PawportSelectDescription, ...] = (
    PawportSelectDescription(
        key="time_to_close",
        translation_key="time_to_close",
        entity_category=EntityCategory.CONFIG,
        options=["5", "10", "15", "30"],
        value_fn=lambda s: s.open_time,
        command="set_open_time",
        argument="durationSeconds",
    ),
    PawportSelectDescription(
        key="open_angle",
        translation_key="open_angle",
        entity_category=EntityCategory.CONFIG,
        options=["90", "120"],
        value_fn=lambda s: s.open_angle,
        command="set_left_angle",
        argument="angle",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door select settings."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportSelect(coordinator, door_id, d) for d in SELECTS],
    )


class PawportSelect(PawportDoorEntity, SelectEntity):
    """A door select setting."""

    entity_description: PawportSelectDescription

    @property
    def current_option(self) -> str | None:
        """Return the current option, or None if the door reports another value."""
        state = self.door_state
        value = self.entity_description.value_fn(state) if state else None
        option = None if value is None else str(value)
        return option if option in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        description = self.entity_description
        await self.async_send(description.command, {description.argument: int(option)})
