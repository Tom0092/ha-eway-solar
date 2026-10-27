"""Energy today across midnight."""
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .test_sensor import TODAY, TOTAL, channel, send, setup, value


async def at(hass, freezer, when):
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_energy_today_starts_from_zero_at_midnight(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))

    await at(hass, freezer, "2026-10-20 23:59:59+02:00")
    assert value(hass, TODAY) == 3284
    await at(hass, freezer, "2026-10-21 00:00:00+02:00")
    assert value(hass, TODAY) == 0
    assert value(hass, TOTAL) == 364.257


async def test_first_message_of_the_day_counts_up_from_zero(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await at(hass, freezer, "2026-10-21 00:00:00+02:00")

    freezer.move_to("2026-10-21 08:00:00+02:00")
    await send(hass, channel(1, 5, 199.805), channel(2, 3, 164.46))
    assert value(hass, TODAY) == 8
    assert value(hass, TOTAL) == 364.265
