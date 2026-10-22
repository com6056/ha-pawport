"""Tests for pet and tag entities."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pawport.const import DOMAIN, SCAN_INTERVAL
from custom_components.pawport.models import Account, Pet, Tag

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
    assert hass.states.get("sensor.biscuit_last_door_event").state == "came_in"
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


async def test_today_follows_the_pawport_home(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Days are the home's, not Home Assistant's, since that's how the cloud counts them."""
    await hass.config.async_set_time_zone("Asia/Tokyo")
    # 10:00 on 2026-10-06 at the home, already 2026-10-07 in Tokyo.
    freezer.move_to("2026-10-06 17:00:00+00:00")
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.biscuit_trips_outside_today").state == "1"
    # The trip time is the same instant whatever zone Home Assistant is in.
    assert hass.states.get("sensor.biscuit_last_trip").state == "2026-10-06T17:30:00+00:00"


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
    assert hass.states.get("sensor.biscuit_last_door_event").state == "came_in"


async def test_pet_opened_the_door_from_inside(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    """Opening from inside is reported as just that, never as the pet being outside."""
    transits = pawport.context["pets"][0]["latestActivity"]["activity"]["transits"]
    transits.append({"doorID": "x", "transitAt": "2026-10-06T18:00:00Z", "location": 1})
    await setup_entry(hass, config_entry)
    state = hass.states.get("sensor.biscuit_last_door_event")
    assert state.state == "opened_from_inside"
    assert state.attributes["options"] == ["came_in", "opened_from_inside"]


async def test_pet_without_activity(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    pawport.context["pets"][0]["latestActivity"] = None
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.biscuit_last_door_event").state == "unknown"
    assert hass.states.get("sensor.biscuit_last_trip").state == "unknown"
    assert hass.states.get("sensor.biscuit_trips_outside_today").state == "0"


async def test_tag_entities(
    hass: HomeAssistant, pawport: FakePawport, config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, config_entry)
    # The cloud reports the tag's coin cell voltage, 2.96 V here.
    assert hass.states.get("sensor.biscuit_s_tag_battery").state == "80"
    voltage = er.async_get(hass).async_get("sensor.biscuit_s_tag_battery_voltage")
    assert voltage is not None
    assert voltage.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("binary_sensor.biscuit_s_tag_connectivity").state == "on"
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"tag_{TAG_ID}"), config_entry.entry_id
    )
    assert device is not None
    assert device.model == "Smart Pet Tag"


async def test_tag_junk_battery_reading_is_unknown(
    hass: HomeAssistant,
    pawport: FakePawport,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    # Tags sometimes report 1 V right after a door pass. That isn't an empty
    # battery, so it reads unknown rather than 0% until a real reading returns.
    pawport.context["tags"][0]["batteryLevel"] = 1
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.biscuit_s_tag_battery").state == "unknown"

    pawport.context["tags"][0]["batteryLevel"] = 3.1
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.biscuit_s_tag_battery").state == "92"


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
    assert hass.states.get("sensor.mochi_last_door_event") is not None
    assert hass.states.get("sensor.mochi_s_tag_battery") is not None

    # A pet or tag removed from the account goes unavailable, then loses its
    # device on the next setup.
    pawport.context["pets"] = pawport.context["pets"][1:]
    pawport.context["tags"] = pawport.context["tags"][1:]
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.biscuit_last_door_event").state == "unavailable"
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
    assert pet.last_transit.opened_from_inside is None
    assert pet.last_transit.door_id is None
    no_date = Pet.from_api({"petID": "x", "latestActivity": {}})
    assert no_date.activity is not None
    assert no_date.activity.day is None
    assert no_date.last_transit is None


def test_tag_model_edge_cases() -> None:
    # The app's scale: 2.0 V is empty and 3.2 V full. A fresh cell reads 3.24.
    assert Tag.from_api({"tagID": "t", "batteryLevel": 3.24}).battery_level == 100
    assert Tag.from_api({"tagID": "t", "batteryLevel": 2.6}).battery_level == 50
    assert Tag.from_api({"tagID": "t", "batteryLevel": 1.9}).battery_level == 0
    assert Tag.from_api({"tagID": "t", "batteryLevel": 2.0}).battery_level == 0
    assert Tag.from_api({"tagID": "t", "batteryLevel": 1.5}).battery_voltage == 1.5
    # A junk reading (seen live right after a door pass) is no reading at all.
    for junk in (1, 0, 1.49, -1):
        tag = Tag.from_api({"tagID": "t", "batteryLevel": junk})
        assert tag.battery_voltage is None
        assert tag.battery_level is None
    assert Tag.from_api({"tagID": "t", "batteryLevel": 3}).battery_voltage == 3.0
    assert Tag.from_api({"tagID": "t", "batteryLevel": True}).battery_level is None
    tag = Tag.from_api({"tagID": "t"})
    assert tag.name == "Smart Pet Tag"
    assert tag.pet_id is None
    assert tag.battery_level is None


def _account(homes: list[dict[str, str]], transit_at: str, door_id: str = "d1") -> Account:
    return Account.from_api(
        {
            "userID": 1,
            "homes": homes,
            "doors": [{"doorID": "d1", "homeID": "h1"}, {"doorID": "d2", "homeID": "h2"}],
            "pets": [
                {
                    "petID": "p",
                    "latestActivity": {
                        "activity": {
                            "transits": [
                                {"doorID": door_id, "transitAt": transit_at, "location": 1}
                            ]
                        }
                    },
                }
            ],
        }
    )


def test_transit_times_use_the_door_home_zone() -> None:
    homes = [
        {"homeID": "h1", "timezone": "America/Los_Angeles"},
        {"homeID": "h2", "timezone": "Europe/Berlin"},
    ]
    la = _account(homes, "2026-10-15 15:28:58").pets["p"]
    assert la.last_transit is not None
    assert la.last_transit.transit_at == datetime(2026, 10, 15, 22, 28, 58, tzinfo=UTC)
    assert la.timezone == ZoneInfo("America/Los_Angeles")
    berlin = _account(homes, "2026-10-15 15:28:58", door_id="d2").pets["p"]
    assert berlin.last_transit is not None
    assert berlin.last_transit.transit_at == datetime(2026, 10, 15, 13, 28, 58, tzinfo=UTC)
    assert berlin.timezone == ZoneInfo("Europe/Berlin")
    # An offset in the value wins over the home's zone.
    explicit = _account(homes, "2026-10-15T15:28:58Z").pets["p"]
    assert explicit.last_transit is not None
    assert explicit.last_transit.transit_at == datetime(2026, 10, 15, 15, 28, 58, tzinfo=UTC)


def test_transit_times_without_a_known_zone() -> None:
    # A door on an unknown home falls back to the account's first home.
    first = _account(
        [{"homeID": "h1", "timezone": "America/Los_Angeles"}], "2026-10-15 15:00:00", "d2"
    )
    assert first.pets["p"].timezone == ZoneInfo("America/Los_Angeles")
    # No usable zone at all: read as UTC rather than dropped.
    for homes in ([], [{"homeID": "h1", "timezone": "Not/AZone"}], [{"homeID": "h1"}]):
        pet = _account(homes, "2026-10-15 15:00:00").pets["p"]
        assert pet.timezone is None
        assert pet.last_transit is not None
        assert pet.last_transit.transit_at == datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
