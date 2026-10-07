"""Hold-open switch for Pawport."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities

PARALLEL_UPDATES = 1

DESCRIPTION = SwitchEntityDescription(key="hold_open", translation_key="hold_open")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hold-open switch."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportHoldOpenSwitch(coordinator, door_id, DESCRIPTION)],
    )


class PawportHoldOpenSwitch(PawportDoorEntity, SwitchEntity):
    """Holds the door open until switched off."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the door is being held open."""
        state = self.door_state
        return state.held_open if state else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Hold the door open."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_held_open(self.door_id, True)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Release the door."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_held_open(self.door_id, False)
        )
