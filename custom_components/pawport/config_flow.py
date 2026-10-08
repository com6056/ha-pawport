"""Config flow for Pawport.

Pawport signs in with an emailed one-time code. Asking for the code also says
whether the account has a password, and only then is a password offered,
since the app gives most accounts no way to set one. Google and Apple sign-in
are not supported: their ID tokens are issued to Pawport's own app and cannot
be obtained from Home Assistant.

A password is stored so a rejected token can be replaced silently; with a
code, a rejected token means a reauthentication prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    PawportAuthError,
    PawportClient,
    PawportConnectionError,
    PawportError,
    PawportInvalidCodeError,
    PawportSession,
)
from .const import CONF_AUTH_TOKEN, CONF_CODE, CONF_REFRESH_TOKEN, DOMAIN, LOGGER

EMAIL_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL))}
)
CODE_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})
PASSWORD_SCHEMA = vol.Schema(
    {vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)
SIGN_IN_METHODS = ["code", "password"]


class PawportConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pawport."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._email = ""
        self._client: PawportClient | None = None
        self._password_supported = False

    @property
    def client(self) -> PawportClient:
        """Return the flow's client, created on first use."""
        if self._client is None:
            self._client = PawportClient(async_get_clientsession(self.hass))
        return self._client

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the account email."""
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            # Before anything is emailed: a code for an account that is
            # already set up could only end in already_configured.
            self._async_abort_entries_match({CONF_EMAIL: self._email})
            return await self.async_step_send_code()
        return self.async_show_form(step_id="user", data_schema=EMAIL_SCHEMA)

    async def async_step_method(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer the password as an alternative, for accounts that have one."""
        return self.async_show_menu(
            step_id="method",
            menu_options=SIGN_IN_METHODS,
            description_placeholders={"email": self._email},
        )

    async def async_step_send_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Email a sign-in code, then ask for it (or offer the password)."""
        try:
            self._password_supported = await self.client.request_email_code(self._email)
        except PawportConnectionError:
            return self.async_abort(reason="cannot_connect")
        except PawportAuthError:
            return self.async_abort(reason="invalid_email")
        except PawportError:
            LOGGER.exception("Unexpected error requesting a sign-in code")
            return self.async_abort(reason="unknown")
        if self._password_supported:
            return await self.async_step_method()
        return await self.async_step_code()

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Exchange the emailed code for a session."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                session = await self.client.verify_email_code(self._email, user_input[CONF_CODE])
            except PawportInvalidCodeError:
                errors["base"] = "invalid_code"
            except PawportAuthError:
                errors["base"] = "invalid_auth"
            except PawportConnectionError:
                errors["base"] = "cannot_connect"
            except PawportError:
                LOGGER.exception("Unexpected error verifying a sign-in code")
                errors["base"] = "unknown"
            else:
                return await self._async_finish(session, password=None)
        return self.async_show_form(
            step_id="code",
            data_schema=CODE_SCHEMA,
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with a password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                session = await self.client.login_password(self._email, password)
            except PawportAuthError:
                errors["base"] = "invalid_auth"
            except PawportConnectionError:
                errors["base"] = "cannot_connect"
            except PawportError:
                LOGGER.exception("Unexpected error signing in with a password")
                errors["base"] = "unknown"
            else:
                return await self._async_finish(session, password=password)
        return self.async_show_form(
            step_id="password",
            data_schema=PASSWORD_SCHEMA,
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in again, to switch method, change the password, or follow an email change.

        The account itself cannot change: signing in to a different Pawport
        account aborts, because entity and device IDs belong to this one.
        """
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            return await self.async_step_send_code()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                EMAIL_SCHEMA, {CONF_EMAIL: entry.data[CONF_EMAIL]}
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication for an expired session."""
        self._email = entry_data[CONF_EMAIL]
        return await self.async_step_send_code()

    async def _async_finish(
        self, session: PawportSession, *, password: str | None
    ) -> ConfigFlowResult:
        """Create or update the entry, keyed on the account's user ID."""
        try:
            account = await self.client.get_account()
        except PawportError:
            LOGGER.exception("Signed in, but the account could not be read")
            return self.async_abort(reason="cannot_connect")

        data = {
            CONF_EMAIL: self._email,
            CONF_AUTH_TOKEN: session.auth_token,
            CONF_REFRESH_TOKEN: session.refresh_token,
        }
        if password is not None:
            data[CONF_PASSWORD] = password

        await self.async_set_unique_id(account.user_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=data, title=self._email
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._email, data=data)
