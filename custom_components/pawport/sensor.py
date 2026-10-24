"""Sensors for Pawport doors, pets, and tags."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PawportConfigEntry
from .entity import (
    PawportDoorEntity,
    PawportPetEntity,
    PawportTagEntity,
    async_add_door_feature_entities,
    async_add_new_entities,
)
from .models import DoorState, Pet, Tag

PARALLEL_UPDATES = 0

type SensorValue = int | float | str | datetime | None


@dataclass(frozen=True, kw_only=True)
class DoorSensorDescription(SensorEntityDescription):
    """Describes a door sensor."""

    value_fn: Callable[[DoorState], SensorValue]
    # Whether the door has the hardware this reads; no entity until it does.
    exists_fn: Callable[[DoorState], bool] | None = None


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
    Days follow the Pawport home's time zone, as the cloud counts them.
    """
    return pet.activity is not None and pet.activity.day == dt_util.now(pet.timezone).date()


def _last_door_event(pet: Pet) -> str | None:
    transit = pet.last_transit
    if transit is None or transit.opened_from_inside is None:
        return None
    return "opened_from_inside" if transit.opened_from_inside else "came_in"


DOOR_SENSORS: tuple[DoorSensorDescription, ...] = (
    DoorSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.battery_level,
        # The battery is an optional accessory; without one the door reads 0.
        exists_fn=lambda s: s.has_battery is True,
    ),
)

PET_SENSORS: tuple[PetSensorDescription, ...] = (
    PetSensorDescription(
        key="last_door_event",
        translation_key="last_door_event",
        device_class=SensorDeviceClass.ENUM,
        options=["came_in", "opened_from_inside"],
        value_fn=_last_door_event,
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
    TagSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda t: t.battery_voltage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door, pet, and tag sensors."""
    coordinator = entry.runtime_data
    async_add_door_feature_entities(
        coordinator,
        async_add_entities,
        DOOR_SENSORS,
        lambda description, state: (
            description.exists_fn is None or (state is not None and description.exists_fn(state))
        ),
        lambda door_id, description: DoorSensor(coordinator, door_id, description),
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
    def available(self) -> bool:
        """Unavailable if the hardware this reads was removed."""
        state = self.door_state
        if not super().available or state is None:
            return False
        exists = self.entity_description.exists_fn
        return exists is None or exists(state)

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


class TagSensor(PawportTagEntity, RestoreSensor):
    """A tag reading that keeps its last good value.

    A tag only reports when it passes the door, and sometimes reports a junk
    battery voltage that the model turns into no reading. The cell hasn't
    changed, so the last good value stands until the next real one, across a
    restart too. A tag removed from the account still goes unavailable.
    """

    entity_description: TagSensorDescription
    _last: SensorValue = None

    async def async_added_to_hass(self) -> None:
        """Restore the last good value, then take the current reading."""
        await super().async_added_to_hass()
        data = await self.async_get_last_sensor_data()
        if data is not None and isinstance(data.native_value, int | float):
            self._last = data.native_value
        self._update_last()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_last()
        super()._handle_coordinator_update()

    def _update_last(self) -> None:
        tag = self.tag
        value = self.entity_description.value_fn(tag) if tag else None
        if value is not None:
            self._last = value

    @property
    def native_value(self) -> SensorValue:
        """Return the last good reading."""
        return self._last
