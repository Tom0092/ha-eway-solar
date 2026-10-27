"""Energy counters, fed through MQTT the way the inverter sends them.

The figures are the ones measured on a 2-panel VN2T08EU-016212C (#1) and the
dusk behaviour reported in #3.
"""
import json

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.eway_solar.const import CONF_MODEL, CONF_SERIAL, DOMAIN

MODEL, SERIAL = "VN2T08EU-016212C", "123456789"
TOPIC = f"/{MODEL}/{SERIAL}/data/post"
TODAY = "sensor.eway_vn2t08eu_016212c_energy_today"
TOTAL = "sensor.eway_vn2t08eu_016212c_energy_total"


def channel(sort, today, total):
    return {"sort": sort, "rssi": -64, "inputVoltage": 30.0, "InputCurrent": 1.0,
            "gridVoltage": 239.6, "gridFreq": 50.0, "genPower": 100.0,
            "genPowerToDay": today, "genPowerTotal": total, "temperature": 30.0,
            "errCode": 0, "duration": 10369356}


async def setup(hass):
    # The daily counter follows the local calendar day, so pin the zone.
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MODEL: MODEL, CONF_SERIAL: SERIAL})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def send(hass, *channels):
    async_fire_mqtt_message(hass, TOPIC, json.dumps(list(channels)))
    await hass.async_block_till_done()


def value(hass, entity_id):
    return float(hass.states.get(entity_id).state)


async def test_energy_is_summed_over_channels(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    assert value(hass, TODAY) == 3284
    assert value(hass, TOTAL) == 364.257


async def test_single_channel_is_unchanged(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8))
    assert value(hass, TODAY) == 1853
    assert value(hass, TOTAL) == 199.8


async def test_message_missing_a_channel_dents_nothing(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await send(hass, channel(1, 1860, 199.807))
    assert value(hass, TODAY) == 1860 + 1431
    # Energy total is total_increasing: a drop of more than 10% would be taken
    # as a meter reset and the whole lifetime yield counted again.
    assert value(hass, TOTAL) == 364.264


async def test_dusk_zero_is_held(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await send(hass, channel(1, 0, 0), channel(2, 0, 0))
    assert value(hass, TODAY) == 3284
    assert value(hass, TOTAL) == 364.257


async def test_new_day_starts_afresh(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    freezer.move_to("2026-10-21 08:00:00+02:00")
    await send(hass, channel(1, 5, 199.805), channel(2, 3, 164.46))
    assert value(hass, TODAY) == 8
    assert value(hass, TOTAL) == 364.265
