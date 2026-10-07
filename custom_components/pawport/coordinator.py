"""Polling coordinator for one Pawport account."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PawportAuthError, PawportClient, PawportError
from .const import CONF_AUTH_TOKEN, CONF_REFRESH_TOKEN, DOMAIN, LOGGER, SCAN_INTERVAL
from .models import Account

if TYPE_CHECKING:
    from . import PawportConfigEntry


class PawportCoordinator(DataUpdateCoordinator[Account]):
    """Polls ``authDataGet`` and owns the account's client."""

    config_entry: PawportConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PawportConfigEntry, client: PawportClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> Account:
        """Fetch the account, signing in again once if the token was rejected."""
        try:
            return await self._with_relogin(self.client.get_account)
        except PawportAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except PawportError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_command(self, command: Callable[[], Awaitable[None]]) -> None:
        """Run a door command, then poll at once so entities show the result."""
        try:
            await self._with_relogin(command)
        except PawportAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except PawportError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # Not async_request_refresh: its debouncer would hold back the poll
        # after a second command within 10 seconds and show a stale state.
        await self.async_refresh()

    async def _with_relogin[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """Run call; on a rejected token, sign in with the stored password and retry.

        Pawport's refresh endpoint is not live, so a dead token can only be
        replaced by signing in again. With a stored password that happens
        here, silently. Without one, the auth error propagates and Home
        Assistant asks the user to reauthenticate with an emailed code.
        """
        try:
            return await call()
        except PawportAuthError:
            password = self.config_entry.data.get(CONF_PASSWORD)
            if not password:
                raise
            LOGGER.debug("Token rejected; signing in again with the stored password")
            session = await self.client.login_password(self.config_entry.data[CONF_EMAIL], password)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_AUTH_TOKEN: session.auth_token,
                    CONF_REFRESH_TOKEN: session.refresh_token,
                },
            )
            return await call()
