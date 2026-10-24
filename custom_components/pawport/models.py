"""Typed views of the Pawport account data.

Parsed from the ``authDataGet`` GraphQL query. This module has no Home
Assistant imports so the client can be tested and reused on its own.

Every field the cloud might omit is optional here: the schema is not
published, so a missing key must degrade one entity, not the whole poll.
Units and encodings follow how the Pawport app itself renders each field.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from typing import Any

# PET_TRANSIT_LOCATION in the app: where the pet was when it opened the door.
TRANSIT_FROM_INSIDE = 1
TRANSIT_FROM_OUTSIDE = 2

# doorStates.chargerDetails, read the way the app reads it (its hasDoorBattery,
# isDoorPluggedIn and isCharging). The isPluggedIn and isCharging fields
# themselves read false on a door that is plugged in, and the app ignores them.
CHARGER_PLUGGED_IN = 0
CHARGER_PLUGGED_IN_WITH_BATTERY = 1
CHARGER_CHARGING = 2
CHARGER_ON_BATTERY = 3
_CHARGER_STATES = frozenset(
    {CHARGER_PLUGGED_IN, CHARGER_PLUGGED_IN_WITH_BATTERY, CHARGER_CHARGING, CHARGER_ON_BATTERY}
)

# doors[].sensors[].sensorType, from the app's isSmartPetDoorInsideSensor,
# isSmartPetDoorOutsideSensor, isOutdoorPetDoorSensor and isExternalSensor.
SENSOR_INSIDE = 1
SENSOR_OUTSIDE = 2
SENSOR_OUTDOOR_DOOR = 3
SENSOR_EXTERNAL = 4

# tags.batteryLevel is the coin cell's voltage. The app's TagBatteryLevel
# shows (volts - 2.0) / 1.2 as the charge, so 2.0 V is empty and 3.2 V full.
_TAG_EMPTY_VOLTS = 2.0
_TAG_RANGE_VOLTS = 1.2
# Tags sometimes report 1 V right after a door pass and are back to ~3.1 V on
# the next one. The app shows that as an empty battery; this floor is ours,
# from those live readings. A coin cell under 2.0 V is already flat to the
# tag, so anything below 1.5 V is a junk reading, not a dying cell.
_TAG_MIN_PLAUSIBLE_VOLTS = 1.5

# doorStates.doorActivityIndicator, the app's doorActivityIndicatorCodes. The
# low bits are the motion and +16/+32 say a panel button or a command caused
# it (OPEN_COMMAND is 35, CLOSED_BUTTON 20). 5-7 are jam, self-tuning and
# alarm. The app's isDoorOpen is "opening or open, from any source".
_ACTIVITY_STATES = {1: "opening", 2: "closing", 3: "open", 4: "closed"}
_ACTIVITY_SELF_TUNING = 6
_ACTIVITY_PROBLEMS = frozenset({5, 7})  # JAM, ALARM
_ACTIVITY_SOURCES = (0, 16, 32)

# The door reports some brightness levels with a +128 flag; the app subtracts
# it from anything above this.
_LED_FLAG_THRESHOLD = 6
_LED_FLAG = 128


def _parse_time(value: Any, zone: tzinfo | None = None) -> datetime | None:
    """Parse a timestamp, returning None for anything that is not one.

    Some fields carry no offset. ``transitAt`` is the home's local time (the
    app shows it in ``homes[].timezone``), so callers pass that zone; anything
    else without an offset is UTC, like ``createdAt``.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone or UTC)
    return parsed


def timezone_names(user_context: dict[str, Any]) -> set[str]:
    """Return the time zone names the account's homes use.

    Resolving a zone can read the zone database from disk, so the caller does
    that off the event loop and hands the results to ``Account.from_api``.
    """
    return {
        name
        for home in user_context.get("homes") or []
        if isinstance(home, dict) and isinstance(name := home.get("timezone"), str) and name
    }


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


def _rgb(value: Any) -> tuple[int, int, int] | None:
    """Return a ``{red green blue}`` object as a tuple, or None if any part is missing."""
    if not isinstance(value, dict):
        return None
    parts = [_as_int(value.get(k)) for k in ("red", "green", "blue")]
    if any(p is None for p in parts):
        return None
    red, green, blue = (max(0, min(int(p or 0), 255)) for p in parts)
    return red, green, blue


@dataclass(frozen=True, slots=True)
class DoorState:
    """Live state of one door, from ``doorStates``."""

    door_id: str
    locked: bool | None
    activity: int | None
    battery_level: int | None
    charger: int | None
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
    led_color: tuple[int, int, int] | None = None
    inside_range: int | None = None
    outside_range: int | None = None
    control_panel_lockout: bool | None = None
    rain_lock_enabled: bool | None = None
    lightning_lock_enabled: bool | None = None
    rain_lock_active: bool | None = None
    lightning_lock_active: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def _activity_motion(self) -> int | None:
        """Return the low bits of a recognised activity code, or None."""
        if self.activity is None or self.activity < 0:
            return None
        source, motion = self.activity & ~0xF, self.activity & 0xF
        return motion if source in _ACTIVITY_SOURCES else None

    @property
    def problem(self) -> bool | None:
        """Return whether the door last reported a jam or an alarm.

        Self-tuning is the door calibrating itself, not a fault. Anything the
        app doesn't name (UNKNOWN, UNASSIGNED) reads as unknown.
        """
        motion = self._activity_motion()
        if motion in _ACTIVITY_PROBLEMS:
            return True
        if motion in _ACTIVITY_STATES or motion == _ACTIVITY_SELF_TUNING:
            return False
        return None

    @property
    def open_state(self) -> str | None:
        """Return opening, open, closing or closed, or None for anything else.

        ``behavior`` looks like the obvious source but stays null while the
        door is held open (seen live in October 2026); the app reads this.
        """
        motion = self._activity_motion()
        return None if motion is None else _ACTIVITY_STATES.get(motion)

    @property
    def has_battery(self) -> bool | None:
        """Return whether a battery is fitted (it is an optional accessory)."""
        if self.charger not in _CHARGER_STATES:
            return None
        return self.charger != CHARGER_PLUGGED_IN

    @property
    def plugged_in(self) -> bool | None:
        """Return whether the door is on mains power."""
        if self.charger not in _CHARGER_STATES:
            return None
        return self.charger != CHARGER_ON_BATTERY

    @property
    def charging(self) -> bool | None:
        """Return whether the battery is charging."""
        if self.charger not in _CHARGER_STATES:
            return None
        return self.charger == CHARGER_CHARGING

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
            activity=_as_int(data.get("doorActivityIndicator")),
            # The app caps the reading at 100.
            battery_level=None if battery is None else min(battery, 100),
            charger=_as_int(data.get("chargerDetails")),
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
            led_color=_rgb(data.get("ledColor")),
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
class SensorModule:
    """One of a door's sensor modules, from ``doors[].sensors``."""

    sensor_type: int
    connected: bool | None
    firmware_version: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SensorModule | None:
        """Build from one ``sensors`` element, or None without a type."""
        sensor_type = _as_int(data.get("sensorType"))
        if sensor_type is None:
            return None
        firmware = data.get("firmwareVersion")
        return cls(
            sensor_type=sensor_type,
            connected=_as_bool(data.get("isConnected")),
            firmware_version=firmware if isinstance(firmware, str) else None,
        )


@dataclass(frozen=True, slots=True)
class Door:
    """A door on the account, with its live state when the cloud has one."""

    door_id: str
    name: str
    home_id: str | None
    state: DoorState | None
    sensors: dict[int, SensorModule] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Transit:
    """One pass of a pet through a door."""

    transit_at: datetime
    location: int | None
    door_id: str | None

    @property
    def opened_from_inside(self) -> bool | None:
        """Return True if the pet opened the door from inside, False if it came in.

        Opening from inside doesn't mean the pet went out. The cloud only knows
        a trip happened once the pet comes back in, which is how the app reads
        it too, so this never claims a pet is outside.
        """
        if self.location == TRANSIT_FROM_INSIDE:
            return True
        if self.location == TRANSIT_FROM_OUTSIDE:
            return False
        return None

    @classmethod
    def from_api(
        cls, data: dict[str, Any], zones: Mapping[str, tzinfo], default_zone: tzinfo | None
    ) -> Transit | None:
        """Build from one ``transits`` element, or None without a timestamp.

        ``zones`` maps a door to its home's time zone, which ``transitAt`` is in.
        """
        door_id = data.get("doorID")
        zone = zones.get(str(door_id), default_zone) if door_id else default_zone
        transit_at = _parse_time(data.get("transitAt"), zone)
        if transit_at is None:
            return None
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
    def from_api(
        cls,
        data: dict[str, Any],
        zones: Mapping[str, tzinfo] | None = None,
        default_zone: tzinfo | None = None,
    ) -> Activity:
        """Build from a ``latestActivity`` object."""
        transits = [
            t
            for raw in (data.get("activity") or {}).get("transits") or []
            if isinstance(raw, dict)
            and (t := Transit.from_api(raw, zones or {}, default_zone)) is not None
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
    # The time zone of the pet's home, which its activity days follow.
    timezone: tzinfo | None = None

    @property
    def last_transit(self) -> Transit | None:
        """Return the most recent pass through a door, if any."""
        if self.activity is None or not self.activity.transits:
            return None
        return self.activity.transits[-1]

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        zones: Mapping[str, tzinfo] | None = None,
        default_zone: tzinfo | None = None,
    ) -> Pet:
        """Build from one ``pets`` element."""
        latest = data.get("latestActivity")
        activity = (
            Activity.from_api(latest, zones, default_zone) if isinstance(latest, dict) else None
        )
        zone = default_zone
        if activity is not None and activity.transits:
            door_id = activity.transits[-1].door_id
            zone = (zones or {}).get(door_id or "", default_zone)
        return cls(
            pet_id=str(data["petID"]),
            name=data.get("name") or "Pet",
            species=(data.get("species") or {}).get("name"),
            activity=activity,
            timezone=zone,
        )


@dataclass(frozen=True, slots=True)
class Tag:
    """A Smart Pet Tag on the account."""

    tag_id: str
    name: str
    pet_id: str | None
    battery_voltage: float | None
    is_online: bool | None

    @property
    def battery_level(self) -> int | None:
        """Return the charge in percent, worked out the way the app does."""
        if self.battery_voltage is None:
            return None
        fraction = (self.battery_voltage - _TAG_EMPTY_VOLTS) / _TAG_RANGE_VOLTS
        return round(max(0.0, min(fraction, 1.0)) * 100)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Tag:
        """Build from one ``tags`` element."""
        volts = data.get("batteryLevel")
        pet_id = data.get("petID")
        return cls(
            tag_id=str(data["tagID"]),
            name=data.get("name") or "Smart Pet Tag",
            pet_id=str(pet_id) if pet_id else None,
            battery_voltage=(
                float(volts)
                if isinstance(volts, int | float)
                and not isinstance(volts, bool)
                and volts >= _TAG_MIN_PLAUSIBLE_VOLTS
                else None
            ),
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
    def from_api(
        cls, user_context: dict[str, Any], timezones: Mapping[str, tzinfo] | None = None
    ) -> Account:
        """Build from the ``userContext`` object.

        ``timezones`` maps the names from ``timezone_names`` to resolved
        zones. A home whose zone is missing from it falls back to the
        account's first known zone, then to UTC.
        """
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
                home_id=str(d["homeID"]) if d.get("homeID") else None,
                state=states.get(door_id),
                sensors={
                    sensor.sensor_type: sensor
                    for raw in d.get("sensors") or []
                    if isinstance(raw, dict) and (sensor := SensorModule.from_api(raw)) is not None
                },
            )
        homes: dict[str, tzinfo] = {}
        for home in user_context.get("homes") or []:
            if (
                isinstance(home, dict)
                and home.get("homeID")
                and (zone := (timezones or {}).get(str(home.get("timezone")))) is not None
            ):
                homes[str(home["homeID"])] = zone
        zones = {
            door_id: homes[door.home_id]
            for door_id, door in doors.items()
            if door.home_id and door.home_id in homes
        }
        default_zone = next(iter(homes.values()), None)
        profile = user_context.get("profile") or {}
        return cls(
            user_id=str(user_context.get("userID")),
            email=profile.get("emailAddress"),
            doors=doors,
            pets=_by_id(
                user_context.get("pets"),
                "petID",
                lambda data: Pet.from_api(data, zones, default_zone),
            ),
            tags=_by_id(user_context.get("tags"), "tagID", Tag.from_api),
            lock_schedules=_by_id(
                user_context.get("doorLockSchedules"), "doorLockScheduleID", LockSchedule.from_api
            ),
            light_schedules=_by_id(
                user_context.get("doorLightSchedules"), "doorID", LightSchedule.from_api
            ),
            raw=user_context,
        )
