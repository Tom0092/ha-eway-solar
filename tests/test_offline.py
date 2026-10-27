"""What the sensors show once the inverter stops publishing at dusk."""
from datetime import timedelta

from homeassistant.const import STATE_UNAVAILABLE
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .test_sensor import TODAY, TOTAL, channel, send, setup

PREFIX = "sensor.eway_vn2t08eu_016212c_"
POWER, PANEL_POWER = PREFIX + "solar_power", PREFIX + "panel_1_power"
LIVE = [PREFIX + "grid_voltage", PREFIX + "panel_1_voltage",
        PREFIX + "panel_1_temperature", PREFIX + "wifi_signal", PREFIX + "fault"]
OPERATING_TIME = PREFIX + "operating_time"


async def wait(hass, freezer, minutes):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def state(hass, entity_id):
    return hass.states.get(entity_id).state


async def test_quiet_inverter_reads_zero_power(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await wait(hass, freezer, 11)

    assert state(hass, POWER) == "0"
    assert state(hass, PANEL_POWER) == "0"
    assert all(state(hass, e) == STATE_UNAVAILABLE for e in LIVE)
    # Counters keep their value through the night.
    assert float(state(hass, TODAY)) == 3284
    assert float(state(hass, TOTAL)) == 364.257
    assert float(state(hass, OPERATING_TIME)) == 10369356


async def test_each_message_puts_it_off(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await wait(hass, freezer, 8)
    await send(hass, channel(1, 1860, 199.807), channel(2, 1435, 164.461))
    await wait(hass, freezer, 4)

    assert float(state(hass, POWER)) == 200
    assert all(state(hass, e) != STATE_UNAVAILABLE for e in LIVE)

    await wait(hass, freezer, 7)
    assert state(hass, POWER) == "0"


async def test_readings_return_with_the_next_message(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await wait(hass, freezer, 11)
    freezer.move_to("2026-10-21 08:00:00+02:00")
    await send(hass, channel(1, 5, 199.805), channel(2, 3, 164.46))

    assert float(state(hass, POWER)) == 200
    assert float(state(hass, PREFIX + "grid_voltage")) == 239.6
    assert all(state(hass, e) != STATE_UNAVAILABLE for e in LIVE)
