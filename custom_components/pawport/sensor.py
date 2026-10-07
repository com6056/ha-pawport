"""Sensors for Pawport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities
from .models import DoorState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PawportSensorDescription(SensorEntityDescription):
    """Describes a door sensor."""

    value_fn: Callable[[DoorState], int | None]


SENSORS: tuple[PawportSensorDescription, ...] = (
    PawportSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.battery_level,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door sensors."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportSensor(coordinator, door_id, d) for d in SENSORS],
    )


class PawportSensor(PawportDoorEntity, SensorEntity):
    """A numeric door reading."""

    entity_description: PawportSensorDescription

    @property
    def native_value(self) -> int | None:
        """Return the reading."""
        state = self.door_state
        return self.entity_description.value_fn(state) if state else None
