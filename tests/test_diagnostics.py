"""The diagnostics download."""
import json

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .test_sensor import SERIAL, channel, send, setup


async def test_diagnostics_show_recent_messages_and_trackers(
    hass, hass_client, mqtt_mock, freezer
):
    started = dt_util.utcnow()
    freezer.move_to("2026-10-20 18:00:00+02:00")
    await setup(hass)
    for wh in range(1840, 1852):
        await send(hass, channel(1, wh, 199.8), channel(2, 1431, 164.457))
    await send(hass, channel(1, 0, 0), channel(2, 0, 0))

    entry = hass.config_entries.async_entries("eway_solar")[0]
    freezer.move_to(started)  # back to when the test client's token was issued
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diag["entry"]["model"] == "VN2T08EU-016212C"
    assert SERIAL not in json.dumps(diag)
    assert len(diag["recent_messages"]) == 10
    # Newest last: the dusk zero is there as the device sent it ...
    assert diag["recent_messages"][-1]["payload"][0]["genPowerToDay"] == 0
    # ... next to what the sensors made of it.
    assert diag["energy_today_per_channel"]["1"] == {"day": "2026-10-20", "value": 1851}
    assert diag["energy_total_per_channel"] == {"1": 199.8, "2": 164.457}
    assert diag["sensors"]["energy_today"] == 3282
