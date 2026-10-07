"""Base entity for Pawport doors."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import PawportCoordinator
from .models import Door, DoorState


class PawportDoorEntity(CoordinatorEntity[PawportCoordinator]):
    """An entity belonging to one door."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PawportCoordinator, door_id: str, description: EntityDescription
    ) -> None:
        """Initialize for one door."""
        super().__init__(coordinator)
        self.entity_description = description
        self.door_id = door_id
        self._attr_unique_id = f"{door_id}_{description.key}"
        door = self.door
        state = door.state if door else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, door_id)},
            manufacturer=MANUFACTURER,
            model="Smart Pet Door",
            name=door.name if door else None,
            sw_version=state.firmware_version if state else None,
        )

    @property
    def door(self) -> Door | None:
        """Return this door from the latest poll."""
        return self.coordinator.data.doors.get(self.door_id)

    @property
    def door_state(self) -> DoorState | None:
        """Return this door's live state from the latest poll."""
        door = self.door
        return door.state if door else None

    @property
    def available(self) -> bool:
        """Available while the poll succeeds and the door reports state."""
        return super().available and self.door_state is not None


def async_add_door_entities(
    coordinator: PawportCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[str], Iterable[Entity]],
) -> None:
    """Add entities for every door, including doors added to the account later."""
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = set(coordinator.data.doors) - known
        if not new:
            return
        known.update(new)
        async_add_entities(entity for door_id in sorted(new) for entity in factory(door_id))

    _add_new()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_add_new))
