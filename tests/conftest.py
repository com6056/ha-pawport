"""Fixtures for Pawport tests.

Tests drive the real client against ``FakePawport``, an in-memory stand-in
for the cloud API mounted on Home Assistant's aiohttp mocker, so the whole
path from entity to HTTP request is exercised.
"""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.pawport.api import API_URL, GRAPHQL_URL
from custom_components.pawport.const import CONF_AUTH_TOKEN, CONF_REFRESH_TOKEN, DOMAIN

EMAIL = "pet-owner@example.com"
PASSWORD = "hunter2"
TOKEN = "11111111-2222-3333-4444-555555555555"
NEW_TOKEN = "66666666-7777-8888-9999-000000000000"
CODE = "123456"
USER_ID = "4242"
DOOR_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

DOOR_STATE: dict[str, Any] = {
    "doorID": DOOR_ID,
    "behavior": None,
    "powerState": 1,
    "batteryChargeLevel": 87,
    "doorLocked": 1,
    "firmwareVersion": "2.4.1",
    "latestAvailableFirmwareVersion": "2.4.1",
    "isFirmwareUpdateAvailable": False,
    "isPluggedIn": False,
    "isCharging": False,
    "offlineSince": None,
    "updatedAt": "2026-10-06T20:00:00.000Z",
    "openTime": 10,
    "leftAngle": 90,
    "speakerVolume": 3,
    "soundEnabled": True,
    "ledEnabled": True,
    "ledBrightness": 132,  # level 4 with the door's +128 flag
    "insideRange": 2,
    "outsideRange": 3,
    "controlPanelLockout": False,
    "rainLockEnabled": True,
    "lightningLockEnabled": False,
    "rainLockActive": False,
    "lightningLockActive": False,
}

PET_ID = "pet-1"
TAG_ID = "tag-1"
ACTIVITY_DAY = "2026-10-06"

PET: dict[str, Any] = {
    "petID": PET_ID,
    "name": "Biscuit",
    "species": {"name": "Dog"},
    "latestActivity": {
        "date": ACTIVITY_DAY,
        "timeOutsideTotal": 1800,
        "tripsOutside": 1,
        "activity": {
            "transits": [
                # Out at 10:00, back in at 10:30 (location is where the pet
                # opened the door from: 1 inside, 2 outside).
                {"doorID": DOOR_ID, "transitAt": "2026-10-06T17:30:00Z", "location": 2},
                {"doorID": DOOR_ID, "transitAt": "2026-10-06T17:00:00Z", "location": 1},
            ]
        },
    },
}

TAG: dict[str, Any] = {
    "tagID": TAG_ID,
    "name": "Biscuit's tag",
    "petID": PET_ID,
    "batteryLevel": 0.8,
    "isOnline": True,
}

SCHEDULE_ID = "sched-1"

LOCK_SCHEDULE: dict[str, Any] = {
    "doorLockScheduleID": SCHEDULE_ID,
    "doorID": DOOR_ID,
    "name": "Night",
    "isEnabled": True,
    "startTime": "21:00",
    "endTime": "06:00",
    "permission": "IN_ONLY",
    "days": {
        "Mon": True,
        "Tue": True,
        "Wed": True,
        "Thu": True,
        "Fri": True,
        "Sat": False,
        "Sun": False,
    },
}

LIGHT_SCHEDULE: dict[str, Any] = {
    "doorID": DOOR_ID,
    "isEnabled": False,
    "startTime": "19:00",
    "endTime": "07:00",
    "days": {
        "Mon": True,
        "Tue": True,
        "Wed": True,
        "Thu": True,
        "Fri": True,
        "Sat": True,
        "Sun": True,
    },
}

# sendDoorCommand command -> (argument, doorStates field) for plain settings.
SETTINGS: dict[str, tuple[str, str]] = {
    "set_sound_enabled": ("enable", "soundEnabled"),
    "set_leds_enabled": ("enable", "ledEnabled"),
    "set_control_panel_lockout": ("enable", "controlPanelLockout"),
    "set_rain_lock_enabled": ("enable", "rainLockEnabled"),
    "set_lightning_lock_enabled": ("enable", "lightningLockEnabled"),
    "set_volume": ("volume", "speakerVolume"),
    "set_brightness": ("ledBrightness", "ledBrightness"),
    "set_inside_range": ("range", "insideRange"),
    "set_outside_range": ("range", "outsideRange"),
    "set_open_time": ("durationSeconds", "openTime"),
    "set_left_angle": ("angle", "leftAngle"),
}


def user_context() -> dict[str, Any]:
    """Return a fresh ``userContext`` for one door."""
    return {
        "userID": USER_ID,
        "profile": {"emailAddress": EMAIL},
        "doors": [{"doorID": DOOR_ID, "name": "Dog Door", "homeID": "home-1"}],
        "doorStates": [copy.deepcopy(DOOR_STATE)],
        "pets": [copy.deepcopy(PET)],
        "tags": [copy.deepcopy(TAG)],
        "doorLockSchedules": [copy.deepcopy(LOCK_SCHEDULE)],
        "doorLightSchedules": [copy.deepcopy(LIGHT_SCHEDULE)],
    }


class FakePawport:
    """In-memory Pawport cloud.

    Holds account state that door commands mutate, accepts exactly one
    valid token at a time, and lets a test override any endpoint's response.
    """

    def __init__(self) -> None:
        """Start with one locked door and TOKEN as the valid session."""
        self.context = user_context()
        self.valid_token = TOKEN
        self.issue_token = NEW_TOKEN
        self.code = CODE
        self.password = PASSWORD
        self.overrides: dict[str, AiohttpClientMockResponse | Exception] = {}
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.codes_sent: list[str] = []
        self.mocker: AiohttpClientMocker | None = None

    def install(self, mocker: AiohttpClientMocker) -> None:
        """Mount the fake API on the aiohttp mocker."""
        self.mocker = mocker
        mocker.post(GRAPHQL_URL, side_effect=self._graphql)
        for path in ("/user", "/user/verify", "/user/password"):
            mocker.post(f"{API_URL}/api/public/auth{path}", side_effect=self._rest)

    def door_state(self) -> dict[str, Any]:
        """Return the mutable state of the one door."""
        state: dict[str, Any] = self.context["doorStates"][0]
        return state

    def _respond(self, method: str, url: Any, status: int, body: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    def _override(self, key: str, method: str, url: Any) -> AiohttpClientMockResponse | None:
        override = self.overrides.get(key)
        if isinstance(override, Exception):
            return AiohttpClientMockResponse(method, url, exc=override)
        return override

    async def _rest(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        path = url.path.removeprefix("/api/public/auth")
        if (override := self._override(path, method, url)) is not None:
            return override
        if path == "/user":
            self.codes_sent.append(data["emailAddress"])
            return self._respond(method, url, 200, {"message": "Verification code sent"})
        if path == "/user/verify":
            if data["verificationCode"] != self.code:
                return self._respond(
                    method,
                    url,
                    422,
                    {
                        "message": "Validation error",
                        "errors": {"verificationCode": ["Verification code has expired"]},
                    },
                )
        elif data["password"] != self.password:
            return self._respond(
                method,
                url,
                422,
                {
                    "message": "Validation error",
                    "errors": {"credentials": ["Invalid email address or password"]},
                },
            )
        self.valid_token = self.issue_token
        return self._respond(method, url, 200, {"authToken": self.issue_token})

    async def _graphql(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        operation = data["operationName"]
        if (override := self._override(operation, method, url)) is not None:
            return override
        headers = self.mocker.mock_calls[-1][3] if self.mocker else {}
        if headers.get("x-auth-token") != self.valid_token:
            return self._respond(
                method,
                url,
                200,
                {
                    "errors": [
                        {"message": "Not authenticated", "extensions": {"code": "UNAUTHENTICATED"}}
                    ]
                },
            )
        if operation == "authDataGet":
            return self._respond(method, url, 200, {"data": {"userContext": self.context}})
        variables = data["variables"]
        if operation == "doorLockScheduleEnabledSet":
            self.commands.append((operation, variables))
            for schedule in self.context["doorLockSchedules"]:
                if schedule["doorLockScheduleID"] == variables["doorLockScheduleID"]:
                    schedule["isEnabled"] = variables["enabled"]
            return self._respond(method, url, 200, {"data": {operation: True}})
        if operation == "doorLightScheduleEnabledSet":
            self.commands.append((operation, variables))
            for schedule in self.context["doorLightSchedules"]:
                if schedule["doorID"] == variables["doorID"]:
                    schedule["isEnabled"] = variables["enabled"]
            return self._respond(method, url, 200, {"data": {operation: True}})
        self.commands.append((variables["command"], variables["arguments"]))
        state = self.door_state()
        if variables["command"] == "door_lock":
            state["doorLocked"] = 1 if variables["arguments"]["locked"] else 0
        elif variables["command"] == "force_open":
            state["behavior"] = "force_open" if variables["arguments"]["forceOpen"] else None
        elif variables["command"] in SETTINGS:
            argument, state_field = SETTINGS[variables["command"]]
            state[state_field] = variables["arguments"][argument]
        else:
            return self._respond(
                method,
                url,
                200,
                {"errors": [{"message": f"unknown command {variables['command']}"}]},
            )
        return self._respond(method, url, 200, {"data": {"sendDoorCommand": True}})


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/pawport in every test."""


@pytest.fixture
def pawport(aioclient_mock: AiohttpClientMocker) -> FakePawport:
    """Return the fake Pawport cloud, mounted."""
    fake = FakePawport()
    fake.install(aioclient_mock)
    return fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return an entry signed in with an emailed code (no stored password)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=USER_ID,
        data={CONF_EMAIL: EMAIL, CONF_AUTH_TOKEN: TOKEN, CONF_REFRESH_TOKEN: None},
    )


@pytest.fixture
def password_entry() -> MockConfigEntry:
    """Return an entry signed in with a stored password."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=USER_ID,
        data={
            CONF_EMAIL: EMAIL,
            CONF_AUTH_TOKEN: TOKEN,
            CONF_REFRESH_TOKEN: None,
            CONF_PASSWORD: PASSWORD,
        },
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
