"""Switches for Pawport doors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PawportConfigEntry
from .entity import PawportDoorEntity, async_add_door_entities
from .models import DoorState

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
