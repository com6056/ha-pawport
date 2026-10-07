"""Door lock for Pawport."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities

PARALLEL_UPDATES = 1

DESCRIPTION = LockEntityDescription(key="lock", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the door lock."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportLock(coordinator, door_id, DESCRIPTION)],
    )


class PawportLock(PawportDoorEntity, LockEntity):
    """The door lock, as in the Pawport app."""

    @property
    def is_locked(self) -> bool | None:
        """Return whether the door is locked."""
        state = self.door_state
        return state.locked if state else None

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_locked(self.door_id, True)
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_locked(self.door_id, False)
        )
