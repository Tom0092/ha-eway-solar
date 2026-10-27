"""Energy counters across a Home Assistant restart."""
from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from .test_sensor import TODAY, TOTAL, channel, send, setup, value


def restore(hass, today, total, saved_at):
    """What Home Assistant saved for both counters before it stopped."""
    saved_at = dt_util.parse_datetime(saved_at)
    mock_restore_cache_with_extra_data(hass, [
        (State(entity_id, str(v), last_updated=saved_at),
         {"native_value": v, "native_unit_of_measurement": unit})
        for entity_id, v, unit in ((TODAY, today, "Wh"), (TOTAL, total, "kWh"))
    ])


async def test_counters_show_their_value_straight_after_restart(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 20:00:00+02:00")
    restore(hass, 3284, 364.257, "2026-10-20 18:10:00+02:00")
    await setup(hass)
    assert value(hass, TODAY) == 3284
    assert value(hass, TOTAL) == 364.257


async def test_dusk_zero_right_after_restart_is_held(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:20:00+02:00")
    restore(hass, 3284, 364.257, "2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 0, 0), channel(2, 0, 0))
    assert value(hass, TODAY) == 3284
    assert value(hass, TOTAL) == 364.257


async def test_message_missing_a_channel_right_after_restart(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    restore(hass, 3284, 364.257, "2026-10-20 11:55:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1860, 199.807))
    assert value(hass, TODAY) == 3284
    assert value(hass, TOTAL) == 364.257

    await send(hass, channel(1, 1860, 199.807), channel(2, 1435, 164.461))
    assert value(hass, TODAY) == 3295
    assert value(hass, TOTAL) == 364.268


async def test_yesterdays_yield_is_not_restored_as_today(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-21 07:00:00+02:00")
    restore(hass, 3284, 364.257, "2026-10-20 18:10:00+02:00")
    await setup(hass)
    assert hass.states.get(TODAY).state == "unknown"
    assert value(hass, TOTAL) == 364.257

    await send(hass, channel(1, 5, 199.805), channel(2, 3, 164.46))
    assert value(hass, TODAY) == 8
    assert value(hass, TOTAL) == 364.265
