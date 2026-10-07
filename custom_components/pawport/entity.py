"""Base entities for Pawport doors, pets, and tags."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import PawportCoordinator
from .models import Account, Door, DoorState, Pet, Tag


def pet_identifier(pet_id: str) -> str:
    """Return the device identifier for a pet."""
    return f"pet_{pet_id}"


def tag_identifier(tag_id: str) -> str:
    """Return the device identifier for a tag."""
    return f"tag_{tag_id}"


def device_identifiers(account: Account) -> set[str]:
    """Return the identifier of every device the account currently has."""
    return (
        set(account.doors)
        | {pet_identifier(p) for p in account.pets}
        | {tag_identifier(t) for t in account.tags}
    )


class PawportEntity(CoordinatorEntity[PawportCoordinator]):
    """Base for every Pawport entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PawportCoordinator, object_id: str, description: EntityDescription
    ) -> None:
        """Initialize for one door, pet, or tag."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{object_id}_{description.key}"


class PawportDoorEntity(PawportEntity):
    """An entity belonging to one door."""

    def __init__(
        self, coordinator: PawportCoordinator, door_id: str, description: EntityDescription
    ) -> None:
        """Initialize for one door."""
        super().__init__(coordinator, door_id, description)
        self.door_id = door_id
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

    async def async_send(self, command: str, arguments: dict[str, object]) -> None:
        """Send a command to this door and refresh."""
        await self.coordinator.async_command(
            lambda: self.coordinator.client.send_door_command(self.door_id, command, arguments)
        )


class PawportPetEntity(PawportEntity):
    """An entity belonging to one pet."""

    def __init__(
        self, coordinator: PawportCoordinator, pet_id: str, description: EntityDescription
    ) -> None:
        """Initialize for one pet."""
        super().__init__(coordinator, pet_identifier(pet_id), description)
        self.pet_id = pet_id
        pet = self.pet
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pet_identifier(pet_id))},
            name=pet.name if pet else None,
            model=pet.species if pet else None,
        )

    @property
    def pet(self) -> Pet | None:
        """Return this pet from the latest poll."""
        return self.coordinator.data.pets.get(self.pet_id)

    @property
    def available(self) -> bool:
        """Available while the poll succeeds and the pet is on the account."""
        return super().available and self.pet is not None


class PawportTagEntity(PawportEntity):
    """An entity belonging to one Smart Pet Tag."""

    def __init__(
        self, coordinator: PawportCoordinator, tag_id: str, description: EntityDescription
    ) -> None:
        """Initialize for one tag."""
        super().__init__(coordinator, tag_identifier(tag_id), description)
        self.tag_id = tag_id
        tag = self.tag
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tag_identifier(tag_id))},
            manufacturer=MANUFACTURER,
            model="Smart Pet Tag",
            name=tag.name if tag else None,
        )

    @property
    def tag(self) -> Tag | None:
        """Return this tag from the latest poll."""
        return self.coordinator.data.tags.get(self.tag_id)

    @property
    def available(self) -> bool:
        """Available while the poll succeeds and the tag is on the account."""
        return super().available and self.tag is not None


def async_add_new_entities(
    coordinator: PawportCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    ids: Callable[[Account], Iterable[str]],
    factory: Callable[[str], Iterable[Entity]],
    *,
    remove_gone: tuple[str, Callable[[str], str]] | None = None,
) -> None:
    """Add entities for every object ``ids`` yields, including ones added later.

    Objects that own a device (doors, pets, tags) are cleaned up through the
    device registry. For ones that do not, such as schedules, ``remove_gone``
    names the entity platform and maps an object ID to its entity's unique ID,
    and the entity is removed from the registry once the object disappears.
    """
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        current = set(ids(coordinator.data))
        if remove_gone is not None:
            platform, unique_id = remove_gone
            registry = er.async_get(coordinator.hass)
            for gone in known - current:
                if entity_id := registry.async_get_entity_id(platform, DOMAIN, unique_id(gone)):
                    registry.async_remove(entity_id)
            known.intersection_update(current)
        new = current - known
        if not new:
            return
        known.update(new)
        async_add_entities(entity for object_id in sorted(new) for entity in factory(object_id))

    _add_new()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


def async_add_door_entities(
    coordinator: PawportCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[str], Iterable[Entity]],
) -> None:
    """Add entities for every door, including doors added to the account later."""
    async_add_new_entities(coordinator, async_add_entities, lambda a: a.doors, factory)
