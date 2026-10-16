"""The door itself, as a cover: open it and hold it open, or close it."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityDescription
from homeassistant.components.cover.const import CoverDeviceClass, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities

PARALLEL_UPDATES = 1

DESCRIPTION = CoverEntityDescription(key="door", name=None, device_class=CoverDeviceClass.DOOR)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the door cover."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportDoor(coordinator, door_id, DESCRIPTION)],
    )


class PawportDoor(PawportDoorEntity, CoverEntity):
    """The door flap, held open until closed, like the app's Open and Close."""

    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    @property
    def _open_state(self) -> str | None:
        state = self.door_state
        return state.open_state if state else None

    @property
    def is_closed(self) -> bool | None:
        """Return whether the door is closed."""
        open_state = self._open_state
        return None if open_state is None else open_state == "closed"

    @property
    def is_opening(self) -> bool:
        """Return whether the door is opening."""
        return self._open_state == "opening"

    @property
    def is_closing(self) -> bool:
        """Return whether the door is closing."""
        return self._open_state == "closing"

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the door and hold it open."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_open(self.door_id, True)
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the door."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_open(self.door_id, False)
        )
