"""Binary sensors for Pawport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .coordinator import PawportCoordinator
from .entity import (
    PawportDoorEntity,
    PawportTagEntity,
    async_add_door_entities,
    async_add_new_entities,
)
from .models import (
    SENSOR_EXTERNAL,
    SENSOR_INSIDE,
    SENSOR_OUTDOOR_DOOR,
    SENSOR_OUTSIDE,
    Account,
    DoorState,
    SensorModule,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PawportBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a door binary sensor."""

    value_fn: Callable[[DoorState], bool | None]
    available_fn: Callable[[DoorState], bool] = lambda _: True


BINARY_SENSORS: tuple[PawportBinarySensorDescription, ...] = (
    PawportBinarySensorDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda s: s.charging,
        # The battery is an optional accessory.
        available_fn=lambda s: s.has_battery is True,
    ),
    PawportBinarySensorDescription(
        key="plugged_in",
        translation_key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.plugged_in,
    ),
    PawportBinarySensorDescription(
        key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.online,
    ),
    # On while the weather lock is holding the door shut.
    PawportBinarySensorDescription(
        key="rain_lock_active",
        translation_key="rain_lock_active",
        value_fn=lambda s: s.rain_lock_active,
    ),
    PawportBinarySensorDescription(
        key="lightning_lock_active",
        translation_key="lightning_lock_active",
        value_fn=lambda s: s.lightning_lock_active,
    ),
)

# One per sensor module the door reports, keyed by its sensorType.
SENSOR_MODULES: dict[int, BinarySensorEntityDescription] = {
    sensor_type: BinarySensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for sensor_type, key in (
        (SENSOR_INSIDE, "inside_sensor"),
        (SENSOR_OUTSIDE, "outside_sensor"),
        (SENSOR_OUTDOOR_DOOR, "outdoor_door_sensor"),
        (SENSOR_EXTERNAL, "external_sensor"),
    )
}

TAG_ONLINE = BinarySensorEntityDescription(
    key="online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door and tag binary sensors."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportBinarySensor(coordinator, door_id, d) for d in BINARY_SENSORS],
    )
    async_add_new_entities(
        coordinator,
        async_add_entities,
        _sensor_module_ids,
        lambda object_id: [PawportSensorModule(coordinator, *_split(object_id))],
        remove_gone=(Platform.BINARY_SENSOR, _sensor_module_unique_id),
    )
    async_add_new_entities(
        coordinator,
        async_add_entities,
        lambda a: a.tags,
        lambda tag_id: [PawportTagOnline(coordinator, tag_id, TAG_ONLINE)],
    )


def _sensor_module_ids(account: Account) -> list[str]:
    """Return ``door_id/sensor_type`` for every sensor module this integration knows."""
    return [
        f"{door_id}/{sensor_type}"
        for door_id, door in account.doors.items()
        for sensor_type in door.sensors
        if sensor_type in SENSOR_MODULES
    ]


def _split(object_id: str) -> tuple[str, int]:
    door_id, _, sensor_type = object_id.rpartition("/")
    return door_id, int(sensor_type)


def _sensor_module_unique_id(object_id: str) -> str:
    door_id, sensor_type = _split(object_id)
    return f"{door_id}_{SENSOR_MODULES[sensor_type].key}"


class PawportBinarySensor(PawportDoorEntity, BinarySensorEntity):
    """A boolean door reading."""

    entity_description: PawportBinarySensorDescription

    @property
    def available(self) -> bool:
        """Unavailable when the door lacks the hardware this reads."""
        state = self.door_state
        return (
            super().available and state is not None and self.entity_description.available_fn(state)
        )

    @property
    def is_on(self) -> bool | None:
        """Return the reading."""
        state = self.door_state
        return self.entity_description.value_fn(state) if state else None


class PawportSensorModule(PawportDoorEntity, BinarySensorEntity):
    """Whether one of a door's sensor modules is connected."""

    def __init__(self, coordinator: PawportCoordinator, door_id: str, sensor_type: int) -> None:
        """Initialize for one sensor module."""
        super().__init__(coordinator, door_id, SENSOR_MODULES[sensor_type])
        self.sensor_type = sensor_type

    @property
    def sensor(self) -> SensorModule | None:
        """Return this sensor module from the latest poll."""
        door = self.door
        return door.sensors.get(self.sensor_type) if door else None

    @property
    def available(self) -> bool:
        """Available while the door still reports this sensor module."""
        return self.coordinator.last_update_success and self.sensor is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the sensor module is connected."""
        sensor = self.sensor
        return sensor.connected if sensor else None


class PawportTagOnline(PawportTagEntity, BinarySensorEntity):
    """Whether a Smart Pet Tag is reachable."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the tag is online."""
        tag = self.tag
        return tag.is_online if tag else None
