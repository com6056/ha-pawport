"""Binary sensors for Pawport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities
from .models import DoorState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PawportBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a door binary sensor."""

    value_fn: Callable[[DoorState], bool | None]


BINARY_SENSORS: tuple[PawportBinarySensorDescription, ...] = (
    PawportBinarySensorDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda s: s.is_charging,
    ),
    PawportBinarySensorDescription(
        key="plugged_in",
        translation_key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.is_plugged_in,
    ),
    PawportBinarySensorDescription(
        key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.online,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door binary sensors."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportBinarySensor(coordinator, door_id, d) for d in BINARY_SENSORS],
    )


class PawportBinarySensor(PawportDoorEntity, BinarySensorEntity):
    """A boolean door reading."""

    entity_description: PawportBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the reading."""
        state = self.door_state
        return self.entity_description.value_fn(state) if state else None
