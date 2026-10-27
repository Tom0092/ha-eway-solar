"""Setting up inverters, in particular the second and third on one broker."""
import asyncio

from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.eway_solar.const import CONF_MODEL, CONF_SERIAL, DOMAIN

MODEL = "VN2T08EU-C621202"
FIRST, SECOND, THIRD = "234301150", "234700769", "234700405"


def topic(serial):
    return f"/{MODEL}/{serial}/data/post"


def configure(hass, serial):
    MockConfigEntry(domain=DOMAIN, unique_id=f"{MODEL}_{serial}",
                    data={CONF_MODEL: MODEL, CONF_SERIAL: serial}).add_to_hass(hass)


async def settle(hass):
    # Discovery starts its flows as background tasks.
    await hass.async_block_till_done(wait_background_tasks=True)


def discovered(hass):
    return sorted(
        f["context"]["title_placeholders"]["serial"]
        for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if f["context"]["source"] == SOURCE_MQTT
    )


async def test_every_inverter_is_discovered(hass, mqtt_mock):
    for serial in (FIRST, SECOND, THIRD):
        async_fire_mqtt_message(hass, topic(serial), "[]")
    await settle(hass)
    assert discovered(hass) == sorted([FIRST, SECOND, THIRD])


async def test_discovered_inverter_is_added_on_confirm(hass, mqtt_mock):
    async_fire_mqtt_message(hass, topic(SECOND), "[]")
    await settle(hass)
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MODEL: MODEL, CONF_SERIAL: SECOND}


async def test_configured_inverter_is_not_offered_again(hass, mqtt_mock):
    configure(hass, FIRST)
    async_fire_mqtt_message(hass, topic(FIRST), "[]")
    async_fire_mqtt_message(hass, topic(FIRST), '[{"sort": 1}]')
    await settle(hass)
    assert discovered(hass) == []


async def test_manual_setup_skips_configured_inverter(hass, mqtt_mock):
    configure(hass, FIRST)
    flow = hass.async_create_task(
        hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER}))
    await asyncio.sleep(0.05)  # let the flow subscribe
    # The inverter already set up happens to publish first.
    async_fire_mqtt_message(hass, topic(FIRST), "[]")
    async_fire_mqtt_message(hass, topic(SECOND), "[]")
    result = await flow
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MODEL: MODEL, CONF_SERIAL: SECOND}
    # The discovered card for the same inverter goes with it.
    await settle(hass)
    assert discovered(hass) == []
