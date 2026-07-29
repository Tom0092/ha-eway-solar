"""Sensors built from the inverter's MQTT telemetry.

One payload arrives as a JSON list with one object per MPPT channel, tagged
with "sort". Channel entities are created on first sight rather than from
configuration, so the same code handles the 1-, 2- and 4-panel variants of this
inverter family without the user telling it which they own.
"""
from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CHANNEL_SENSORS, CONF_MODEL, CONF_SERIAL, DEVICE_SENSORS, DOMAIN, data_topic

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    model = entry.data[CONF_MODEL]
    serial = entry.data[CONF_SERIAL]
    topic = data_topic(model, serial)

    device = DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=f"Eway {model}",
        manufacturer="EasyCharging",
        model=model,
        serial_number=serial,
    )

    entities: dict[str, EwaySensor] = {}
    for key, (field, name, unit, dcl, scl, icon) in DEVICE_SENSORS.items():
        entities[key] = EwaySensor(serial, device, key, name, unit, dcl, scl, icon)
    async_add_entities(entities.values())

    known_channels: set[int] = set()

    @callback
    def _on_message(msg: mqtt.ReceiveMessage) -> None:
        _LOGGER.debug("message on %s (%d bytes)", msg.topic, len(msg.payload or b""))
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning("Unparseable payload on %s", msg.topic)
            return
        if isinstance(payload, dict):
            payload = [payload]
        if not payload:
            return

        # Channels appear the first time the inverter reports them, so a panel
        # added later shows up without reconfiguring anything.
        new: list[EwaySensor] = []
        for obj in payload:
            ch = int(obj.get("sort", 1))
            if ch in known_channels:
                continue
            known_channels.add(ch)
            for key, (field, suffix, unit, dcl, scl, icon) in CHANNEL_SENSORS.items():
                ent = EwaySensor(serial, device, f"ch{ch}_{key}",
                                 f"Panel {ch} {suffix}", unit, dcl, scl, icon)
                entities[f"ch{ch}_{key}"] = ent
                new.append(ent)
        if new:
            async_add_entities(new)

        for obj in payload:
            ch = int(obj.get("sort", 1))
            for key, (field, *_rest) in CHANNEL_SENSORS.items():
                ent = entities.get(f"ch{ch}_{key}")
                if ent is not None and field in obj:
                    ent.set_value(obj[field])

        first = payload[0]
        for key, (field, *_rest) in DEVICE_SENSORS.items():
            if field in first:
                entities[key].set_value(first[field])

        # Total across all channels: the device never reports this itself, and
        # it is the figure the Energy dashboard and most dashboards want.
        total = sum(float(o.get("genPower") or 0) for o in payload)
        ent = entities.get("power_total")
        if ent is None:
            ent = EwaySensor(serial, device, "power_total", "Solar power",
                             "W", "power", "measurement", None)
            entities["power_total"] = ent
            async_add_entities([ent])
        ent.set_value(round(total, 2))

    unsub = await mqtt.async_subscribe(hass, topic, _on_message)
    entry.async_on_unload(unsub)
    _LOGGER.debug("Subscribed to %s (unsub=%r)", topic, unsub)


class EwaySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, serial, device, key, name, unit, dcl, scl, icon):
        self._attr_unique_id = f"eway_{serial}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = dcl
        self._attr_state_class = scl
        self._attr_icon = icon
        self._attr_device_info = device
        self._attr_native_value = None

    @callback
    def set_value(self, value) -> None:
        self._attr_native_value = value
        if self.hass is not None:
            self.async_write_ha_state()
