"""Config flow: discover the inverter by listening for its telemetry."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import callback

from .const import CONF_MODEL, CONF_SERIAL, DISCOVERY_TOPIC, DOMAIN

_LOGGER = logging.getLogger(__name__)

# The inverter publishes about once a minute, so this is generous enough to
# catch one message without making the user stare at a spinner for ever.
DISCOVERY_TIMEOUT = 90


class EwaySolarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Listen on the wildcard topic and pick the model/serial out of it.

        Asking the user to type a model string like VN2T08EU-016212C exactly is
        a good way to generate support issues, so we watch for a real message
        instead and only fall back to manual entry if nothing arrives.
        """
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            return self.async_abort(reason="mqtt_unavailable")

        if user_input is not None:
            return await self._create(user_input[CONF_MODEL], user_input[CONF_SERIAL])

        found: asyncio.Future = self.hass.loop.create_future()

        @callback
        def _on_message(msg: mqtt.ReceiveMessage) -> None:
            if found.done():
                return
            # topic looks like /<model>/<serial>/data/post
            parts = msg.topic.strip("/").split("/")
            if len(parts) >= 3 and parts[-2:] == ["data", "post"]:
                found.set_result((parts[0], parts[1]))

        unsub = await mqtt.async_subscribe(self.hass, DISCOVERY_TOPIC, _on_message)
        try:
            model, serial = await asyncio.wait_for(found, DISCOVERY_TIMEOUT)
        except asyncio.TimeoutError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_MODEL): str, vol.Required(CONF_SERIAL): str}
                ),
                errors={"base": "not_discovered"},
                description_placeholders={"topic": DISCOVERY_TOPIC},
            )
        finally:
            unsub()

        return await self._create(model, serial)

    async def _create(self, model: str, serial: str) -> ConfigFlowResult:
        await self.async_set_unique_id(f"{model}_{serial}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Eway {model} ({serial})",
            data={CONF_MODEL: model, CONF_SERIAL: serial},
        )
