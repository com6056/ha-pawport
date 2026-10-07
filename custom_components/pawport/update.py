"""Firmware update status for Pawport doors.

Read-only on purpose: a firmware push from an unofficial client is a risk
worth leaving to the Pawport app.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities

PARALLEL_UPDATES = 0

DESCRIPTION = UpdateEntityDescription(
    key="firmware",
    device_class=UpdateDeviceClass.FIRMWARE,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door firmware status."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportFirmware(coordinator, door_id, DESCRIPTION)],
    )


class PawportFirmware(PawportDoorEntity, UpdateEntity):
    """Whether newer door firmware is available; install it from the Pawport app."""

    @property
    def installed_version(self) -> str | None:
        """Return the running firmware version."""
        state = self.door_state
        return state.firmware_version if state else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest firmware Pawport offers for this door."""
        state = self.door_state
        return (state.latest_firmware_version or state.firmware_version) if state else None
