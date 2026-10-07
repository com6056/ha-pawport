"""Typed views of the Pawport account data.

Parsed from the ``authDataGet`` GraphQL query. This module has no Home
Assistant imports so the client can be tested and reused on its own.

Every field the cloud might omit is optional here: the schema is not
published, so a missing key must degrade one entity, not the whole poll.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _parse_time(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp, returning None for anything else."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    """Return value as an int when it is a number (not a bool), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    return None


def _as_bool(value: Any) -> bool | None:
    """Return value as a bool when it is boolean-like, else None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    return None


@dataclass(frozen=True, slots=True)
class DoorState:
    """Live state of one door, from ``doorStates``."""

    door_id: str
    locked: bool | None
    behavior: Any
    battery_level: int | None
    is_charging: bool | None
    is_plugged_in: bool | None
    firmware_version: str | None
    latest_firmware_version: str | None
    offline_since: datetime | None
    updated_at: datetime | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def held_open(self) -> bool:
        """Return whether the door is being held open.

        Follows homebridge-pawport, the only implementation tested against a
        real door: ``behavior`` is null while the door runs normally and set
        while a force-open is active.
        """
        return self.behavior is not None

    @property
    def online(self) -> bool:
        """Return whether the cloud currently reaches the door."""
        return self.offline_since is None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DoorState:
        """Build from one ``doorStates`` element."""
        locked = data.get("doorLocked")
        return cls(
            door_id=str(data["doorID"]),
            locked=None if locked is None else locked == 1 or locked is True,
            behavior=data.get("behavior"),
            battery_level=_as_int(data.get("batteryChargeLevel")),
            is_charging=_as_bool(data.get("isCharging")),
            is_plugged_in=_as_bool(data.get("isPluggedIn")),
            firmware_version=data.get("firmwareVersion"),
            latest_firmware_version=data.get("latestAvailableFirmwareVersion"),
            offline_since=_parse_time(data.get("offlineSince")),
            updated_at=_parse_time(data.get("updatedAt")),
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class Door:
    """A door on the account, with its live state when the cloud has one."""

    door_id: str
    name: str
    home_id: str | None
    state: DoorState | None


@dataclass(frozen=True, slots=True)
class Account:
    """Everything one ``authDataGet`` poll returns that the integration uses."""

    user_id: str
    email: str | None
    doors: dict[str, Door]
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, user_context: dict[str, Any]) -> Account:
        """Build from the ``userContext`` object."""
        states = {
            str(s["doorID"]): DoorState.from_api(s)
            for s in user_context.get("doorStates") or []
            if isinstance(s, dict) and s.get("doorID")
        }
        doors: dict[str, Door] = {}
        for d in user_context.get("doors") or []:
            if not isinstance(d, dict) or not d.get("doorID"):
                continue
            door_id = str(d["doorID"])
            doors[door_id] = Door(
                door_id=door_id,
                name=d.get("name") or "Pawport",
                home_id=d.get("homeID"),
                state=states.get(door_id),
            )
        profile = user_context.get("profile") or {}
        return cls(
            user_id=str(user_context.get("userID")),
            email=profile.get("emailAddress"),
            doors=doors,
            raw=user_context,
        )
