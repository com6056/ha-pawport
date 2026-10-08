"""Async client for the Pawport cloud API.

No Home Assistant imports: everything HA-specific lives in the integration
modules, so this file can be tested against a fake server on its own and
lifted into a library unchanged if that is ever needed.

The API is not published. Auth is REST under ``/api/public/auth``; reads and
door commands are GraphQL at ``/graphql``, authenticated with an
``x-auth-token`` header.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import aiohttp

from .models import Account

API_URL: Final = "https://api.app.pawport.com"
GRAPHQL_URL: Final = f"{API_URL}/graphql"
USER_AGENT: Final = "ha-pawport"
TIMEOUT: Final = aiohttp.ClientTimeout(total=30)

# Error codes Apollo Server uses for a missing or rejected token.
_AUTH_ERROR_CODES: Final = frozenset({"UNAUTHENTICATED", "FORBIDDEN"})

# The app's own query fields, trimmed to what the integration reads.
ACCOUNT_QUERY: Final = """
query authDataGet {
  userContext {
    userID
    profile { emailAddress }
    doors { doorID name homeID }
    doorStates {
      doorID behavior powerState batteryChargeLevel doorLocked
      firmwareVersion latestAvailableFirmwareVersion isFirmwareUpdateAvailable
      isPluggedIn isCharging offlineSince updatedAt
      openTime leftAngle speakerVolume soundEnabled ledEnabled ledBrightness
      insideRange outsideRange controlPanelLockout
      rainLockEnabled lightningLockEnabled rainLockActive lightningLockActive
    }
    pets {
      petID name species { name }
      latestActivity {
        date timeOutsideTotal tripsOutside
        activity { transits { doorID transitAt location } }
      }
    }
    tags { tagID name petID batteryLevel isOnline }
    doorLockSchedules {
      doorLockScheduleID doorID name isEnabled startTime endTime permission
      days { Mon Tue Wed Thu Fri Sat Sun }
    }
    doorLightSchedules {
      doorID isEnabled startTime endTime
      days { Mon Tue Wed Thu Fri Sat Sun }
    }
  }
}
"""

DOOR_COMMAND_MUTATION: Final = """
mutation sendDoorCommand($command: String!, $doorID: String!, $arguments: json) {
  sendDoorCommand(command: $command, doorID: $doorID, arguments: $arguments)
}
"""


LOCK_SCHEDULE_ENABLED_MUTATION: Final = """
mutation doorLockScheduleEnabledSet($doorLockScheduleID: String!, $enabled: Boolean!) {
  doorLockScheduleEnabledSet(doorLockScheduleID: $doorLockScheduleID, enabled: $enabled)
}
"""

LIGHT_SCHEDULE_ENABLED_MUTATION: Final = """
mutation doorLightScheduleEnabledSet($doorID: String!, $enabled: Boolean!) {
  doorLightScheduleEnabledSet(doorID: $doorID, enabled: $enabled)
}
"""


class PawportError(Exception):
    """Base error for the Pawport client."""


class PawportConnectionError(PawportError):
    """The API could not be reached, or answered with a server error."""


class PawportAuthError(PawportError):
    """The credentials or the stored token were rejected."""


class PawportInvalidCodeError(PawportAuthError):
    """The emailed verification code was wrong or has expired."""


class PawportApiError(PawportError):
    """The API answered, but not in a shape this client understands."""


@dataclass(frozen=True, slots=True)
class PawportSession:
    """Tokens returned by a successful sign-in."""

    auth_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None


def parse_session(payload: Any) -> PawportSession:
    """Extract the session from a sign-in response.

    Pawport answers ``{authToken, refreshToken, expiresIn}`` (seen live in
    October 2026), with ``expiresIn`` at the 32-bit maximum, so sessions do
    not expire in practice. A ``data`` or ``session`` wrapper and an
    ``accessToken``/``token`` spelling are accepted too, in case that ever
    changes. Anything else fails loudly, naming the keys it saw (never their
    values) so a log is enough to fix the parser.
    """
    candidates = [payload]
    if isinstance(payload, dict):
        candidates += [payload.get(k) for k in ("data", "session", "auth")]
    for body in candidates:
        if not isinstance(body, dict):
            continue
        token = body.get("authToken") or body.get("accessToken") or body.get("token")
        if not isinstance(token, str) or not token:
            continue
        refresh = body.get("refreshToken")
        expires_at = None
        expires_in = body.get("expiresIn")
        if isinstance(expires_in, int | float) and expires_in > 0:
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        return PawportSession(
            auth_token=token,
            refresh_token=refresh if isinstance(refresh, str) and refresh else None,
            expires_at=expires_at,
        )
    keys = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
    raise PawportApiError(f"Sign-in response has no token (keys: {keys})")


class PawportClient:
    """Pawport cloud client for one account."""

    def __init__(self, session: aiohttp.ClientSession, auth_token: str | None = None) -> None:
        """Initialize with a shared aiohttp session and an optional token."""
        self._session = session
        self.auth_token = auth_token

    async def request_email_code(self, email: str) -> bool:
        """Ask Pawport to email a one-time sign-in code.

        Returns whether the account also has a password. The app offers no way
        to set one, so for most accounts this is False and the code is the only
        way in.
        """
        payload = await self._rest("/api/public/auth/user", {"emailAddress": email})
        return isinstance(payload, dict) and payload.get("passwordSupported") is True

    async def verify_email_code(self, email: str, code: str) -> PawportSession:
        """Exchange an emailed code for a session and adopt its token."""
        payload = await self._rest(
            "/api/public/auth/user/verify",
            {"emailAddress": email, "verificationCode": code.strip()},
        )
        return self._adopt(parse_session(payload))

    async def login_password(self, email: str, password: str) -> PawportSession:
        """Sign in with email and password and adopt the token."""
        payload = await self._rest(
            "/api/public/auth/user/password",
            {"emailAddress": email, "password": password},
        )
        return self._adopt(parse_session(payload))

    async def get_account(self) -> Account:
        """Fetch the account, its doors, and their live state."""
        data = await self._graphql("authDataGet", ACCOUNT_QUERY)
        context = data.get("userContext")
        if not isinstance(context, dict):
            raise PawportApiError("authDataGet returned no userContext")
        return Account.from_api(context)

    async def send_door_command(
        self, door_id: str, command: str, arguments: dict[str, Any] | None = None
    ) -> None:
        """Send a command to a door; raise unless the cloud accepts it."""
        data = await self._graphql(
            "sendDoorCommand",
            DOOR_COMMAND_MUTATION,
            {"doorID": door_id, "command": command, "arguments": arguments or {}},
        )
        if data.get("sendDoorCommand") is not True:
            raise PawportApiError(f"Door rejected {command}: {data.get('sendDoorCommand')!r}")

    async def set_locked(self, door_id: str, locked: bool) -> None:
        """Lock or unlock a door."""
        await self.send_door_command(door_id, "door_lock", {"locked": locked})

    async def set_held_open(self, door_id: str, held_open: bool) -> None:
        """Hold a door open, or release it."""
        await self.send_door_command(door_id, "force_open", {"forceOpen": held_open})

    async def set_lock_schedule_enabled(self, schedule_id: str, enabled: bool) -> None:
        """Turn a lock schedule on or off."""
        data = await self._graphql(
            "doorLockScheduleEnabledSet",
            LOCK_SCHEDULE_ENABLED_MUTATION,
            {"doorLockScheduleID": schedule_id, "enabled": enabled},
        )
        if data.get("doorLockScheduleEnabledSet") is False:
            raise PawportApiError("Lock schedule change rejected")

    async def set_light_schedule_enabled(self, door_id: str, enabled: bool) -> None:
        """Turn a door's light schedule on or off."""
        data = await self._graphql(
            "doorLightScheduleEnabledSet",
            LIGHT_SCHEDULE_ENABLED_MUTATION,
            {"doorID": door_id, "enabled": enabled},
        )
        if data.get("doorLightScheduleEnabledSet") is False:
            raise PawportApiError("Light schedule change rejected")

    def _adopt(self, session: PawportSession) -> PawportSession:
        self.auth_token = session.auth_token
        return session

    async def _rest(self, path: str, body: dict[str, Any]) -> Any:
        """POST to a public REST endpoint and return the decoded JSON."""
        status, payload = await self._post(f"{API_URL}{path}", body, auth=False)
        if status < 400:
            return payload
        if status in (400, 401, 403, 422):
            raise _rest_error(payload)
        raise PawportApiError(f"{path} answered HTTP {status}")

    async def _graphql(
        self, operation: str, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run a GraphQL operation and return its ``data`` object."""
        if not self.auth_token:
            raise PawportAuthError("No auth token")
        body = {"operationName": operation, "query": query, "variables": variables or {}}
        status, payload = await self._post(GRAPHQL_URL, body, auth=True)
        if status in (401, 403):
            raise PawportAuthError(f"{operation}: token rejected (HTTP {status})")
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            codes = {(e.get("extensions") or {}).get("code") for e in errors if isinstance(e, dict)}
            messages = "; ".join(str(e.get("message")) for e in errors if isinstance(e, dict))
            if codes & _AUTH_ERROR_CODES:
                raise PawportAuthError(f"{operation}: {messages}")
            raise PawportApiError(f"{operation}: {messages}")
        if status >= 400:
            raise PawportApiError(f"{operation} answered HTTP {status}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise PawportApiError(f"{operation} returned no data")
        return data

    async def _post(self, url: str, body: dict[str, Any], *, auth: bool) -> tuple[int, Any]:
        """POST JSON and return (status, decoded body).

        5xx and transport failures become PawportConnectionError, which the
        integration treats as transient. A body that is not JSON decodes to
        None and is judged by the caller from the status alone.
        """
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if auth and self.auth_token:
            headers["x-auth-token"] = self.auth_token
        try:
            async with self._session.post(url, json=body, headers=headers, timeout=TIMEOUT) as resp:
                if resp.status >= 500:
                    raise PawportConnectionError(f"{url} answered HTTP {resp.status}")
                try:
                    payload = await resp.json(content_type=None)
                except ValueError:
                    payload = None
                return resp.status, payload
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PawportConnectionError(f"Cannot reach Pawport: {err}") from err


def _rest_error(payload: Any) -> PawportAuthError:
    """Turn a 4xx auth response into the matching exception.

    Validation failures come back as ``{"message": ..., "errors": {field:
    [messages]}}``; a complaint about ``verificationCode`` is a bad code,
    anything else is bad credentials.
    """
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, dict):
        detail = "; ".join(
            f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
            for k, v in errors.items()
        )
        if "verificationCode" in errors:
            return PawportInvalidCodeError(detail)
        return PawportAuthError(detail)
    message = payload.get("message") if isinstance(payload, dict) else None
    return PawportAuthError(str(message or "Sign-in rejected"))
