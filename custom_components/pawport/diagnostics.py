"""Diagnostics for Pawport."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import PawportConfigEntry
from .const import CONF_AUTH_TOKEN, CONF_REFRESH_TOKEN

TO_REDACT = {
    CONF_AUTH_TOKEN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    "emailAddress",
    "userID",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PawportConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and the raw account poll."""
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "account": async_redact_data(entry.runtime_data.data.raw, TO_REDACT),
    }
