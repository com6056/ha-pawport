"""Constants for the Pawport integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "pawport"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "Pawport"
SCAN_INTERVAL: Final = timedelta(seconds=30)

CONF_AUTH_TOKEN: Final = "auth_token"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_CODE: Final = "code"
