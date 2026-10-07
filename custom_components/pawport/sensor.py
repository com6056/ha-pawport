"""Sensors for Pawport doors, pets, and tags."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PawportConfigEntry
from .entity import (
    PawportDoorEntity,
    PawportPetEntity,
    PawportTagEntity,
    async_add_door_entities,
    async_add_new_entities,
)
from .models import DoorState, Pet, Tag

PARALLEL_UPDATES = 0

type SensorValue = int | str | datetime | None


@dataclass(frozen=True, kw_only=True)
class DoorSensorDescription(SensorEntityDescription):
    """Describes a door sensor."""

    value_fn: Callable[[DoorState], SensorValue]


@dataclass(frozen=True, kw_only=True)
class PetSensorDescription(SensorEntityDescription):
    """Describes a pet sensor."""

    value_fn: Callable[[Pet], SensorValue]


@dataclass(frozen=True, kw_only=True)
class TagSensorDescription(SensorEntityDescription):
    """Describes a tag sensor."""

    value_fn: Callable[[Tag], SensorValue]


def _today(pet: Pet) -> bool:
    """Return whether the pet's latest activity is for today.

    The cloud reports only the latest day with activity, so on a day the pet
    has not used the door yet, today's counts are zero rather than that day's.
    """
    return pet.activity is not None and pet.activity.day == dt_util.now().date()


def _location(pet: Pet) -> str | None:
    transit = pet.last_transit
    if transit is None or transit.went_out is None:
        return None
    return "outside" if transit.went_out else "inside"


DOOR_SENSORS: tuple[DoorSensorDescription, ...] = (
    DoorSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.battery_level,
    ),
)

PET_SENSORS: tuple[PetSensorDescription, ...] = (
    PetSensorDescription(
        key="location",
        translation_key="location",
        device_class=SensorDeviceClass.ENUM,
        options=["inside", "outside"],
        value_fn=_location,
    ),
    PetSensorDescription(
        key="last_trip",
        translation_key="last_trip",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda p: p.last_transit.transit_at if p.last_transit else None,
    ),
    PetSensorDescription(
        key="trips_today",
        translation_key="trips_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: (p.activity.trips_outside or 0) if p.activity and _today(p) else 0,
    ),
    PetSensorDescription(
        key="time_outside_today",
        translation_key="time_outside_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: (p.activity.time_outside or 0) if p.activity and _today(p) else 0,
    ),
)

TAG_SENSORS: tuple[TagSensorDescription, ...] = (
    TagSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.battery_level,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door, pet, and tag sensors."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [DoorSensor(coordinator, door_id, d) for d in DOOR_SENSORS],
    )
    async_add_new_entities(
        coordinator,
        async_add_entities,
        lambda a: a.pets,
        lambda pet_id: [PetSensor(coordinator, pet_id, d) for d in PET_SENSORS],
    )
    async_add_new_entities(
        coordinator,
        async_add_entities,
        lambda a: a.tags,
        lambda tag_id: [TagSensor(coordinator, tag_id, d) for d in TAG_SENSORS],
    )


class DoorSensor(PawportDoorEntity, SensorEntity):
    """A door reading."""

    entity_description: DoorSensorDescription

    @property
    def native_value(self) -> SensorValue:
        """Return the reading."""
        state = self.door_state
        return self.entity_description.value_fn(state) if state else None


class PetSensor(PawportPetEntity, SensorEntity):
    """A pet reading."""

    entity_description: PetSensorDescription

    @property
    def native_value(self) -> SensorValue:
        """Return the reading."""
        pet = self.pet
        return self.entity_description.value_fn(pet) if pet else None


class TagSensor(PawportTagEntity, SensorEntity):
    """A tag reading."""

    entity_description: TagSensorDescription

    @property
    def native_value(self) -> SensorValue:
        """Return the reading."""
        tag = self.tag
        return self.entity_description.value_fn(tag) if tag else None
