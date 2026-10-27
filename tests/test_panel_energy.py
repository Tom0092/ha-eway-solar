"""Energy counters per panel."""
from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from .test_sensor import TODAY, TOTAL, channel, send, setup, value

PREFIX = "sensor.eway_vn2t08eu_016212c_panel_"
P1_TODAY, P1_TOTAL = PREFIX + "1_energy_today", PREFIX + "1_energy_total"
P2_TODAY, P2_TOTAL = PREFIX + "2_energy_today", PREFIX + "2_energy_total"


async def test_each_panel_reports_its_own_energy(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    assert value(hass, P1_TODAY) == 1853
    assert value(hass, P1_TOTAL) == 199.8
    assert value(hass, P2_TODAY) == 1431
    assert value(hass, P2_TOTAL) == 164.457
    assert value(hass, TODAY) == value(hass, P1_TODAY) + value(hass, P2_TODAY)


async def test_dusk_zero_is_held_per_panel(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    await send(hass, channel(1, 0, 0), channel(2, 0, 0))
    assert value(hass, P1_TODAY) == 1853
    assert value(hass, P2_TOTAL) == 164.457


async def test_new_day_starts_afresh_per_panel(hass, mqtt_mock, freezer):
    freezer.move_to("2026-10-20 18:10:00+02:00")
    await setup(hass)
    await send(hass, channel(1, 1853, 199.8), channel(2, 1431, 164.457))
    freezer.move_to("2026-10-21 08:00:00+02:00")
    await send(hass, channel(1, 5, 199.805), channel(2, 3, 164.46))
    assert value(hass, P1_TODAY) == 5
    assert value(hass, P2_TODAY) == 3


async def test_dusk_zero_right_after_restart_is_held_per_panel(hass, mqtt_mock, freezer):
    # Panel sensors are only created by the first message after the restart;
    # that message must not pull them below what was saved.
    freezer.move_to("2026-10-20 18:20:00+02:00")
    saved_at = dt_util.parse_datetime("2026-10-20 18:10:00+02:00")
    mock_restore_cache_with_extra_data(hass, [
        (State(entity_id, str(v), last_updated=saved_at),
         {"native_value": v, "native_unit_of_measurement": unit})
        for entity_id, v, unit in ((P1_TODAY, 1853, "Wh"), (P1_TOTAL, 199.8, "kWh"),
                                   (TODAY, 3284, "Wh"), (TOTAL, 364.257, "kWh"))
    ])
    await setup(hass)
    await send(hass, channel(1, 0, 0))
    assert value(hass, P1_TODAY) == 1853
    assert value(hass, P1_TOTAL) == 199.8
    assert value(hass, TODAY) == 3284
