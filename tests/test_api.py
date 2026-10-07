"""Tests for the HA-free client and models."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.pawport.api import (
    API_URL,
    GRAPHQL_URL,
    PawportApiError,
    PawportAuthError,
    PawportClient,
    PawportConnectionError,
    PawportInvalidCodeError,
    parse_session,
)
from custom_components.pawport.models import Account, DoorState

from .conftest import CODE, DOOR_ID, EMAIL, NEW_TOKEN, PASSWORD, TOKEN, USER_ID, FakePawport


@pytest.fixture
async def client(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[PawportClient]:
    """Return a client on the mocker's session, holding the valid token."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield PawportClient(session, TOKEN)
    await session.close()


def respond(
    status: int, body: Any = None, exc: Exception | None = None
) -> AiohttpClientMockResponse:
    return AiohttpClientMockResponse("post", GRAPHQL_URL, status=status, json=body, exc=exc)


@pytest.mark.parametrize(
    "payload",
    [
        {"authToken": "t"},
        {"accessToken": "t"},
        {"token": "t"},
        {"data": {"authToken": "t"}},
        {"session": {"authToken": "t"}},
    ],
)
def test_parse_session_shapes(payload: dict[str, Any]) -> None:
    assert parse_session(payload).auth_token == "t"


def test_parse_session_refresh_and_expiry() -> None:
    session = parse_session({"authToken": "t", "refreshToken": "r", "expiresIn": 3600})
    assert session.refresh_token == "r"
    assert session.expires_at is not None
    assert session.expires_at > datetime.now(UTC)


def test_parse_session_ignores_bad_extras() -> None:
    session = parse_session({"authToken": "t", "refreshToken": "", "expiresIn": "soon"})
    assert session.refresh_token is None
    assert session.expires_at is None


@pytest.mark.parametrize("payload", [{"user": {"id": 1}}, ["t"], None, {"authToken": ""}])
def test_parse_session_without_token_names_keys(payload: Any) -> None:
    with pytest.raises(PawportApiError) as err:
        parse_session(payload)
    if isinstance(payload, dict):
        assert str(sorted(payload)) in str(err.value)


async def test_sign_in_with_code(client: PawportClient, pawport: FakePawport) -> None:
    client.auth_token = None
    await client.request_email_code(EMAIL)
    assert pawport.codes_sent == [EMAIL]
    session = await client.verify_email_code(EMAIL, f" {CODE} ")
    assert session.auth_token == NEW_TOKEN
    assert client.auth_token == NEW_TOKEN


async def test_wrong_code(client: PawportClient, pawport: FakePawport) -> None:
    with pytest.raises(PawportInvalidCodeError, match="expired"):
        await client.verify_email_code(EMAIL, "000000")


async def test_password(client: PawportClient, pawport: FakePawport) -> None:
    assert (await client.login_password(EMAIL, PASSWORD)).auth_token == NEW_TOKEN
    with pytest.raises(PawportAuthError, match="credentials") as err:
        await client.login_password(EMAIL, "wrong")
    assert not isinstance(err.value, PawportInvalidCodeError)


@pytest.mark.parametrize(
    ("status", "body", "error", "match"),
    [
        (401, {"message": "Nope"}, PawportAuthError, "Nope"),
        (400, "not json", PawportAuthError, "Sign-in rejected"),
        (404, None, PawportApiError, "HTTP 404"),
        (503, None, PawportConnectionError, "HTTP 503"),
    ],
)
async def test_rest_errors(
    client: PawportClient,
    pawport: FakePawport,
    status: int,
    body: Any,
    error: type[Exception],
    match: str,
) -> None:
    pawport.overrides["/user"] = AiohttpClientMockResponse(
        "post", API_URL, status=status, json=body
    )
    with pytest.raises(error, match=match):
        await client.request_email_code(EMAIL)


async def test_get_account(client: PawportClient, pawport: FakePawport) -> None:
    account = await client.get_account()
    assert account.user_id == USER_ID
    assert account.email == EMAIL
    door = account.doors[DOOR_ID]
    assert door.name == "Dog Door"
    assert door.state is not None
    assert door.state.locked is True
    assert door.state.battery_level == 87
    assert door.state.online is True
    assert door.state.held_open is False


async def test_sends_token_header(
    client: PawportClient, pawport: FakePawport, aioclient_mock: AiohttpClientMocker
) -> None:
    await client.get_account()
    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["x-auth-token"] == TOKEN
    assert headers["User-Agent"] == "ha-pawport"


async def test_commands(client: PawportClient, pawport: FakePawport) -> None:
    await client.set_locked(DOOR_ID, False)
    await client.set_held_open(DOOR_ID, True)
    assert pawport.commands == [
        ("door_lock", {"locked": False}),
        ("force_open", {"forceOpen": True}),
    ]


async def test_command_rejected(client: PawportClient, pawport: FakePawport) -> None:
    pawport.overrides["sendDoorCommand"] = respond(200, {"data": {"sendDoorCommand": False}})
    with pytest.raises(PawportApiError, match="rejected door_lock"):
        await client.set_locked(DOOR_ID, True)


async def test_graphql_needs_token(client: PawportClient) -> None:
    client.auth_token = None
    with pytest.raises(PawportAuthError, match="No auth token"):
        await client.get_account()


@pytest.mark.parametrize(
    ("response", "error", "match"),
    [
        (respond(401), PawportAuthError, "HTTP 401"),
        (
            respond(200, {"errors": [{"message": "x", "extensions": {"code": "FORBIDDEN"}}]}),
            PawportAuthError,
            "x",
        ),
        (respond(200, {"errors": [{"message": "boom"}]}), PawportApiError, "boom"),
        (respond(418, {}), PawportApiError, "HTTP 418"),
        (respond(200, {"data": None}), PawportApiError, "no data"),
        (respond(200, {"data": {"userContext": None}}), PawportApiError, "no userContext"),
        (respond(502), PawportConnectionError, "HTTP 502"),
        (respond(200, exc=aiohttp.ClientError("reset")), PawportConnectionError, "reset"),
        (respond(200, exc=TimeoutError()), PawportConnectionError, "Cannot reach"),
    ],
)
async def test_graphql_errors(
    client: PawportClient,
    pawport: FakePawport,
    response: AiohttpClientMockResponse,
    error: type[Exception],
    match: str,
) -> None:
    pawport.overrides["authDataGet"] = response
    with pytest.raises(error, match=match):
        await client.get_account()


def test_models_tolerate_missing_fields() -> None:
    account = Account.from_api(
        {
            "userID": 7,
            "doors": [{"doorID": "d1"}, {"name": "no id"}, "junk"],
            "doorStates": [
                {
                    "doorID": "d1",
                    "doorLocked": None,
                    "batteryChargeLevel": "high",
                    "isCharging": 1,
                    "isPluggedIn": "yes",
                    "offlineSince": "2026-10-06T01:02:03Z",
                    "updatedAt": "not a date",
                },
                {"no": "id"},
            ],
        }
    )
    assert account.user_id == "7"
    assert account.email is None
    assert list(account.doors) == ["d1"]
    door = account.doors["d1"]
    assert door.name == "Pawport"
    state = door.state
    assert state is not None
    assert state.locked is None
    assert state.battery_level is None
    assert state.is_charging is True
    assert state.is_plugged_in is None
    assert state.online is False
    assert state.offline_since == datetime(2026, 10, 6, 1, 2, 3, tzinfo=UTC)
    assert state.updated_at is None


def test_door_state_bool_coercions() -> None:
    state = DoorState.from_api(
        {"doorID": "d", "doorLocked": True, "batteryChargeLevel": 55.6, "isCharging": True}
    )
    assert state.locked is True
    assert state.battery_level == 55
    assert DoorState.from_api({"doorID": "d", "batteryChargeLevel": True}).battery_level is None
