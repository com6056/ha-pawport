"""The Pawport integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PawportClient
from .const import CONF_AUTH_TOKEN, DOMAIN
from .coordinator import PawportCoordinator
from .entity import device_identifiers

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

type PawportConfigEntry = ConfigEntry[PawportCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PawportConfigEntry) -> bool:
    """Set up Pawport from a config entry."""
    client = PawportClient(async_get_clientsession(hass), entry.data[CONF_AUTH_TOKEN])
    coordinator = PawportCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _remove_stale_devices(hass, entry, device_identifiers(coordinator.data))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PawportConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: PawportConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a door, pet, or tag the account no longer has."""
    current = device_identifiers(entry.runtime_data.data)
    return not any(
        identifier[0] == DOMAIN and identifier[1] in current for identifier in device.identifiers
    )


def _remove_stale_devices(
    hass: HomeAssistant, entry: PawportConfigEntry, current: set[str]
) -> None:
    """Remove devices for doors, pets, and tags no longer on the account."""
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        ids = {i[1] for i in device.identifiers if i[0] == DOMAIN}
        if ids and not ids & current:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
