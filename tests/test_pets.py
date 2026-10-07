"""Tests for pet and tag entities."""

from __future__ import annotations

import copy

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pawport.const import DOMAIN, SCAN_INTERVAL
from custom_components.pawport.models import Pet, Tag

from .conftest import PET, PET_ID, TAG, TAG_ID, FakePawport, setup_entry

# 2026-10-06 midday in the test instance's US/Pacific time zone.
SAME_DAY = "2026-10-06 12:00:00-07:00"
NEXT_DAY = "2026-10-07 12:00:00-07:00"


async def test_pet_sensors_today(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to(SAME_DAY)
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.biscuit_location").state == "inside"
    assert hass.states.get("sensor.biscuit_last_trip").state == "2026-10-06T17:30:00+00:00"
    assert hass.states.get("sensor.biscuit_trips_outside_today").state == "1"
    time_outside = hass.states.get("sensor.biscuit_time_outside_today")
    assert float(time_outside.state) == 30
    assert time_outside.attributes["unit_of_measurement"] == "min"

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"pet_{PET_ID}"), config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Biscuit"
    assert device.model == "Dog"


async def test_counts_reset_on_a_new_day(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The cloud only reports the latest active day, which is not today."""
    freezer.move_to(NEXT_DAY)
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.biscuit_trips_outside_today").state == "0"
    assert float(hass.states.get("sensor.biscuit_time_outside_today").state) == 0
    # Where the pet is and when it last moved still come from that day.
    assert hass.states.get("sensor.biscuit_location").state == "inside"


async def test_pet_went_out(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    transits = pawport.context["pets"][0]["latestActivity"]["activity"]["transits"]
    transits.append({"doorID": "x", "transitAt": "2026-10-06T18:00:00Z", "location": 1})
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.biscuit_location").state == "outside"


async def test_pet_without_activity(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.context["pets"][0]["latestActivity"] = None
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.biscuit_location").state == "unknown"
    assert hass.states.get("sensor.biscuit_last_trip").state == "unknown"
    assert hass.states.get("sensor.biscuit_trips_outside_today").state == "0"


async def test_tag_entities(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    # The cloud reports tag battery as a 0-1 fraction.
    assert hass.states.get("sensor.biscuit_s_tag_battery").state == "80"
    assert hass.states.get("binary_sensor.biscuit_s_tag_connectivity").state == "on"
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"tag_{TAG_ID}"), config_entry.entry_id
    )
    assert device is not None
    assert device.model == "Smart Pet Tag"


async def test_pets_and_tags_come_and_go(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    pawport.context["pets"].append({**copy.deepcopy(PET), "petID": "pet-2", "name": "Mochi"})
    pawport.context["tags"].append({**copy.deepcopy(TAG), "tagID": "tag-2", "name": "Mochi's tag"})
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.mochi_location") is not None
    assert hass.states.get("sensor.mochi_s_tag_battery") is not None

    # A pet or tag removed from the account goes unavailable, then loses its
    # device on the next setup.
    pawport.context["pets"] = pawport.context["pets"][1:]
    pawport.context["tags"] = pawport.context["tags"][1:]
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.biscuit_location").state == "unavailable"
    assert hass.states.get("sensor.biscuit_s_tag_battery").state == "unavailable"

    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    assert (
        devices.async_get_device_by_identifier((DOMAIN, f"pet_{PET_ID}"), config_entry.entry_id)
        is None
    )
    assert (
        devices.async_get_device_by_identifier((DOMAIN, f"tag_{TAG_ID}"), config_entry.entry_id)
        is None
    )
    assert (
        devices.async_get_device_by_identifier((DOMAIN, "pet_pet-2"), config_entry.entry_id)
        is not None
    )


def test_pet_model_edge_cases() -> None:
    pet = Pet.from_api(
        {
            "petID": 9,
            "latestActivity": {
                "date": "not a date",
                "activity": {
                    "transits": [{"transitAt": None}, "junk", {"transitAt": "2026-10-06T00:00:00Z"}]
                },
            },
        }
    )
    assert pet.pet_id == "9"
    assert pet.name == "Pet"
    assert pet.species is None
    assert pet.activity is not None
    assert pet.activity.day is None
    assert pet.last_transit is not None
    assert pet.last_transit.went_out is None
    assert pet.last_transit.door_id is None
    no_date = Pet.from_api({"petID": "x", "latestActivity": {}})
    assert no_date.activity is not None
    assert no_date.activity.day is None
    assert no_date.last_transit is None


def test_tag_model_edge_cases() -> None:
    assert Tag.from_api({"tagID": "t", "batteryLevel": 1.7}).battery_level == 100
    assert Tag.from_api({"tagID": "t", "batteryLevel": -1}).battery_level == 0
    assert Tag.from_api({"tagID": "t", "batteryLevel": True}).battery_level is None
    tag = Tag.from_api({"tagID": "t"})
    assert tag.name == "Smart Pet Tag"
    assert tag.pet_id is None
    assert tag.battery_level is None
