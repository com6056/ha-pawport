"""Typed views of the Pawport account data.

Parsed from the ``authDataGet`` GraphQL query. This module has no Home
Assistant imports so the client can be tested and reused on its own.

Every field the cloud might omit is optional here: the schema is not
published, so a missing key must degrade one entity, not the whole poll.
Units and encodings follow how the Pawport app itself renders each field.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# PET_TRANSIT_LOCATION in the app: where the pet was when it opened the door.
TRANSIT_FROM_INSIDE = 1
TRANSIT_FROM_OUTSIDE = 2

# The door reports some brightness levels with a +128 flag; the app subtracts
# it from anything above this.
_LED_FLAG_THRESHOLD = 6
_LED_FLAG = 128


def _parse_time(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp, returning None for anything else."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    """Parse a ``YYYY-MM-DD`` date, returning None for anything else."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
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


def _led_brightness(value: Any) -> int | None:
    """Undo the +128 flag the door sets on some brightness levels."""
    level = _as_int(value)
    if level is not None and level > _LED_FLAG_THRESHOLD:
        level -= _LED_FLAG
    return level


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
    open_time: int | None = None
    open_angle: int | None = None
    speaker_volume: int | None = None
    sound_enabled: bool | None = None
    led_enabled: bool | None = None
    led_brightness: int | None = None
    inside_range: int | None = None
    outside_range: int | None = None
    control_panel_lockout: bool | None = None
    rain_lock_enabled: bool | None = None
    lightning_lock_enabled: bool | None = None
    rain_lock_active: bool | None = None
    lightning_lock_active: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

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
        battery = _as_int(data.get("batteryChargeLevel"))
        return cls(
            door_id=str(data["doorID"]),
            locked=None if locked is None else locked == 1 or locked is True,
            behavior=data.get("behavior"),
            # The app caps the reading at 100.
            battery_level=None if battery is None else min(battery, 100),
            is_charging=_as_bool(data.get("isCharging")),
            is_plugged_in=_as_bool(data.get("isPluggedIn")),
            firmware_version=data.get("firmwareVersion"),
            latest_firmware_version=data.get("latestAvailableFirmwareVersion"),
            offline_since=_parse_time(data.get("offlineSince")),
            updated_at=_parse_time(data.get("updatedAt")),
            open_time=_as_int(data.get("openTime")),
            open_angle=_as_int(data.get("leftAngle")),
            speaker_volume=_as_int(data.get("speakerVolume")),
            sound_enabled=_as_bool(data.get("soundEnabled")),
            led_enabled=_as_bool(data.get("ledEnabled")),
            led_brightness=_led_brightness(data.get("ledBrightness")),
            inside_range=_as_int(data.get("insideRange")),
            outside_range=_as_int(data.get("outsideRange")),
            control_panel_lockout=_as_bool(data.get("controlPanelLockout")),
            rain_lock_enabled=_as_bool(data.get("rainLockEnabled")),
            lightning_lock_enabled=_as_bool(data.get("lightningLockEnabled")),
            rain_lock_active=_as_bool(data.get("rainLockActive")),
            lightning_lock_active=_as_bool(data.get("lightningLockActive")),
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
class Transit:
    """One pass of a pet through a door."""

    transit_at: datetime
    location: int | None
    door_id: str | None

    @property
    def went_out(self) -> bool | None:
        """Return True for an exit, False for an entry, None if unknown."""
        if self.location == TRANSIT_FROM_INSIDE:
            return True
        if self.location == TRANSIT_FROM_OUTSIDE:
            return False
        return None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Transit | None:
        """Build from one ``transits`` element, or None without a timestamp."""
        transit_at = _parse_time(data.get("transitAt"))
        if transit_at is None:
            return None
        door_id = data.get("doorID")
        return cls(
            transit_at=transit_at,
            location=_as_int(data.get("location")),
            door_id=str(door_id) if door_id else None,
        )


@dataclass(frozen=True, slots=True)
class Activity:
    """A pet's activity for one day, from ``latestActivity``."""

    day: date | None
    trips_outside: int | None
    time_outside: int | None
    transits: tuple[Transit, ...]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Activity:
        """Build from a ``latestActivity`` object."""
        transits = [
            t
            for raw in (data.get("activity") or {}).get("transits") or []
            if isinstance(raw, dict) and (t := Transit.from_api(raw)) is not None
        ]
        return cls(
            day=_parse_date(data.get("date")),
            trips_outside=_as_int(data.get("tripsOutside")),
            time_outside=_as_int(data.get("timeOutsideTotal")),
            transits=tuple(sorted(transits, key=lambda t: t.transit_at)),
        )


@dataclass(frozen=True, slots=True)
class Pet:
    """A pet on the account."""

    pet_id: str
    name: str
    species: str | None
    activity: Activity | None

    @property
    def last_transit(self) -> Transit | None:
        """Return the most recent pass through a door, if any."""
        if self.activity is None or not self.activity.transits:
            return None
        return self.activity.transits[-1]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Pet:
        """Build from one ``pets`` element."""
        latest = data.get("latestActivity")
        return cls(
            pet_id=str(data["petID"]),
            name=data.get("name") or "Pet",
            species=(data.get("species") or {}).get("name"),
            activity=Activity.from_api(latest) if isinstance(latest, dict) else None,
        )


@dataclass(frozen=True, slots=True)
class Tag:
    """A Smart Pet Tag on the account."""

    tag_id: str
    name: str
    pet_id: str | None
    battery_level: int | None
    is_online: bool | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Tag:
        """Build from one ``tags`` element."""
        # The app treats batteryLevel as a 0-1 fraction.
        level = data.get("batteryLevel")
        battery = None
        if isinstance(level, int | float) and not isinstance(level, bool):
            battery = round(max(0.0, min(float(level), 1.0)) * 100)
        pet_id = data.get("petID")
        return cls(
            tag_id=str(data["tagID"]),
            name=data.get("name") or "Smart Pet Tag",
            pet_id=str(pet_id) if pet_id else None,
            battery_level=battery,
            is_online=_as_bool(data.get("isOnline")),
        )


_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _days(value: Any) -> tuple[str, ...]:
    """Return the enabled weekdays from a ``days`` object, Monday first."""
    if not isinstance(value, dict):
        return ()
    return tuple(day for day in _DAYS if value.get(day) is True)


@dataclass(frozen=True, slots=True)
class LockSchedule:
    """A schedule that restricts which way pets may pass during a window.

    ``permission`` is the app's enum: ``IN_ONLY``, ``OUT_ONLY`` or
    ``NO_TRANSIT``.
    """

    schedule_id: str
    door_id: str
    name: str
    enabled: bool | None
    start: str | None
    end: str | None
    days: tuple[str, ...]
    permission: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LockSchedule:
        """Build from one ``doorLockSchedules`` element."""
        return cls(
            schedule_id=str(data["doorLockScheduleID"]),
            door_id=str(data.get("doorID")),
            name=data.get("name") or "Schedule",
            enabled=_as_bool(data.get("isEnabled")),
            start=data.get("startTime"),
            end=data.get("endTime"),
            days=_days(data.get("days")),
            permission=data.get("permission"),
        )


@dataclass(frozen=True, slots=True)
class LightSchedule:
    """A door's light schedule; each door has at most one."""

    door_id: str
    enabled: bool | None
    start: str | None
    end: str | None
    days: tuple[str, ...]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LightSchedule:
        """Build from one ``doorLightSchedules`` element."""
        return cls(
            door_id=str(data["doorID"]),
            enabled=_as_bool(data.get("isEnabled")),
            start=data.get("startTime"),
            end=data.get("endTime"),
            days=_days(data.get("days")),
        )


def _by_id[T](items: Any, key: str, build: Callable[[dict[str, Any]], T]) -> dict[str, T]:
    """Build a dict of models from a list, skipping entries without an ID."""
    result: dict[str, T] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get(key):
            model = build(item)
            result[str(item[key])] = model
    return result


@dataclass(frozen=True, slots=True)
class Account:
    """Everything one ``authDataGet`` poll returns that the integration uses."""

    user_id: str
    email: str | None
    doors: dict[str, Door]
    pets: dict[str, Pet] = field(default_factory=dict)
    tags: dict[str, Tag] = field(default_factory=dict)
    lock_schedules: dict[str, LockSchedule] = field(default_factory=dict)
    light_schedules: dict[str, LightSchedule] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, user_context: dict[str, Any]) -> Account:
        """Build from the ``userContext`` object."""
        states: dict[str, DoorState] = _by_id(
            user_context.get("doorStates"), "doorID", DoorState.from_api
        )
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
            pets=_by_id(user_context.get("pets"), "petID", Pet.from_api),
            tags=_by_id(user_context.get("tags"), "tagID", Tag.from_api),
            lock_schedules=_by_id(
                user_context.get("doorLockSchedules"), "doorLockScheduleID", LockSchedule.from_api
            ),
            light_schedules=_by_id(
                user_context.get("doorLightSchedules"), "doorID", LightSchedule.from_api
            ),
            raw=user_context,
        )
