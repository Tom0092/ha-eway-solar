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
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import CONF_MODEL, CONF_SERIAL, DISCOVERY_TOPIC, DOMAIN

_LOGGER = logging.getLogger(__name__)

# The inverter publishes about once a minute, so this is generous enough to
# catch one message without making the user stare at a spinner for ever.
DISCOVERY_TIMEOUT = 90


def _parse_topic(topic: str) -> tuple[str, str] | None:
    """Model and serial from /<model>/<serial>/data/post, or None."""
    parts = topic.strip("/").split("/")
    if len(parts) >= 3 and parts[-2:] == ["data", "post"]:
        return parts[0], parts[1]
    return None


def _unique_id(model: str, serial: str) -> str:
    return f"{model}_{serial}"


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
        configured = self._async_current_ids()

        @callback
        def _on_message(msg: mqtt.ReceiveMessage) -> None:
            if found.done():
                return
            # Skip inverters already set up: with several on one broker, the
            # first message to arrive is as likely as not from one of those.
            parsed = _parse_topic(msg.topic)
            if parsed is not None and _unique_id(*parsed) not in configured:
                found.set_result(parsed)

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

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """Offer each inverter as soon as its telemetry reaches the broker.

        The manifest subscribes to the data topic, so every inverter turns up
        under Discovered on its own, the second and third of an installation
        included. Inverters already set up keep publishing about once a minute
        and are turned away here by their unique ID.
        """
        parsed = _parse_topic(discovery_info.topic)
        if parsed is None:
            return self.async_abort(reason="invalid_discovery_info")
        self._model, self._serial = parsed
        await self.async_set_unique_id(_unique_id(*parsed))
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"model": self._model, "serial": self._serial}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._entry(self._model, self._serial)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"model": self._model, "serial": self._serial},
        )

    async def _create(self, model: str, serial: str) -> ConfigFlowResult:
        # A discovered card for the same inverter may be waiting. Take over
        # rather than give up; the card goes once this entry is created.
        await self.async_set_unique_id(_unique_id(model, serial), raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self._entry(model, serial)

    def _entry(self, model: str, serial: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=f"Eway {model} ({serial})",
            data={CONF_MODEL: model, CONF_SERIAL: serial},
        )
