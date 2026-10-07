"""Switches for Pawport doors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .coordinator import PawportCoordinator
from .entity import PawportDoorEntity, async_add_door_entities, async_add_new_entities
from .models import DoorState, LightSchedule, LockSchedule

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PawportSwitchDescription(SwitchEntityDescription):
    """Describes a door switch and the command that drives it."""

    value_fn: Callable[[DoorState], bool | None]
    command: str
    arguments_fn: Callable[[bool], dict[str, Any]]


SWITCHES: tuple[PawportSwitchDescription, ...] = (
    PawportSwitchDescription(
        key="hold_open",
        translation_key="hold_open",
        value_fn=lambda s: s.held_open,
        command="force_open",
        arguments_fn=lambda on: {"forceOpen": on},
    ),
    PawportSwitchDescription(
        key="sound",
        translation_key="sound",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda s: s.sound_enabled,
        command="set_sound_enabled",
        arguments_fn=lambda on: {"enable": on},
    ),
    PawportSwitchDescription(
        key="lights",
        translation_key="lights",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda s: s.led_enabled,
        command="set_leds_enabled",
        arguments_fn=lambda on: {"enable": on},
    ),
    # The app's "Panel Buttons": on means the buttons on the door work, which
    # the door stores as control-panel lockout being off.
    PawportSwitchDescription(
        key="panel_buttons",
        translation_key="panel_buttons",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda s: None if s.control_panel_lockout is None else not s.control_panel_lockout,
        command="set_control_panel_lockout",
        arguments_fn=lambda on: {"enable": not on},
    ),
    PawportSwitchDescription(
        key="rain_lock",
        translation_key="rain_lock",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda s: s.rain_lock_enabled,
        command="set_rain_lock_enabled",
        arguments_fn=lambda on: {"enable": on},
    ),
    PawportSwitchDescription(
        key="lightning_lock",
        translation_key="lightning_lock",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda s: s.lightning_lock_enabled,
        command="set_lightning_lock_enabled",
        arguments_fn=lambda on: {"enable": on},
    ),
)


LOCK_SCHEDULE = SwitchEntityDescription(
    key="lock_schedule", translation_key="lock_schedule", entity_category=EntityCategory.CONFIG
)
LIGHT_SCHEDULE = SwitchEntityDescription(
    key="light_schedule", translation_key="light_schedule", entity_category=EntityCategory.CONFIG
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up door switches."""
    coordinator = entry.runtime_data
    async_add_door_entities(
        coordinator,
        async_add_entities,
        lambda door_id: [PawportSwitch(coordinator, door_id, d) for d in SWITCHES],
    )
    async_add_new_entities(
        coordinator,
        async_add_entities,
        # Only schedules on a door the account still has, so a removed door's
        # schedules cannot recreate its device.
        lambda a: [k for k, v in a.lock_schedules.items() if v.door_id in a.doors],
        lambda schedule_id: [LockScheduleSwitch(coordinator, schedule_id)],
        remove_gone=(Platform.SWITCH, LockScheduleSwitch.unique_id_for),
    )
    async_add_new_entities(
        coordinator,
        async_add_entities,
        lambda a: [k for k in a.light_schedules if k in a.doors],
        lambda door_id: [LightScheduleSwitch(coordinator, door_id)],
        remove_gone=(Platform.SWITCH, lambda door_id: f"{door_id}_{LIGHT_SCHEDULE.key}"),
    )


class PawportSwitch(PawportDoorEntity, SwitchEntity):
    """A door switch."""

    entity_description: PawportSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return the switch state."""
        state = self.door_state
        return self.entity_description.value_fn(state) if state else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._set(False)

    async def _set(self, on: bool) -> None:
        description = self.entity_description
        await self.async_send(description.command, description.arguments_fn(on))


def _schedule_attributes(schedule: LockSchedule | LightSchedule) -> dict[str, Any]:
    return {
        "start": schedule.start,
        "end": schedule.end,
        "days": list(schedule.days),
    }


class LockScheduleSwitch(PawportDoorEntity, SwitchEntity):
    """Turns one of a door's lock schedules on or off."""

    def __init__(self, coordinator: PawportCoordinator, schedule_id: str) -> None:
        """Initialize for one lock schedule."""
        schedule = coordinator.data.lock_schedules[schedule_id]
        super().__init__(coordinator, schedule.door_id, LOCK_SCHEDULE)
        self.schedule_id = schedule_id
        self._attr_unique_id = self.unique_id_for(schedule_id)
        self._attr_translation_placeholders = {"name": schedule.name}

    @staticmethod
    def unique_id_for(schedule_id: str) -> str:
        """Return the unique ID for a lock schedule's switch."""
        return f"lock_schedule_{schedule_id}"

    @property
    def schedule(self) -> LockSchedule | None:
        """Return this schedule from the latest poll."""
        return self.coordinator.data.lock_schedules.get(self.schedule_id)

    @property
    def available(self) -> bool:
        """Available while the schedule still exists."""
        return self.coordinator.last_update_success and self.schedule is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the schedule is enabled."""
        schedule = self.schedule
        return schedule.enabled if schedule else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return when the schedule applies and what it allows."""
        schedule = self.schedule
        if schedule is None:  # pragma: no cover - not read while unavailable
            return None
        permission = schedule.permission.lower() if schedule.permission else None
        return {**_schedule_attributes(schedule), "permission": permission}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the schedule."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the schedule."""
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_lock_schedule_enabled(self.schedule_id, enabled)
        )


class LightScheduleSwitch(PawportDoorEntity, SwitchEntity):
    """Turns a door's light schedule on or off."""

    def __init__(self, coordinator: PawportCoordinator, door_id: str) -> None:
        """Initialize for one door's light schedule."""
        super().__init__(coordinator, door_id, LIGHT_SCHEDULE)

    @property
    def schedule(self) -> LightSchedule | None:
        """Return this door's light schedule from the latest poll."""
        return self.coordinator.data.light_schedules.get(self.door_id)

    @property
    def available(self) -> bool:
        """Available while the door has a light schedule."""
        return self.coordinator.last_update_success and self.schedule is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the light schedule is enabled."""
        schedule = self.schedule
        return schedule.enabled if schedule else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return when the light schedule applies."""
        schedule = self.schedule
        return _schedule_attributes(schedule) if schedule else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the light schedule."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the light schedule."""
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        await self.coordinator.async_command(
            lambda: self.coordinator.client.set_light_schedule_enabled(self.door_id, enabled)
        )
