"""Sensors built from the inverter's MQTT telemetry.

One payload arrives as a JSON list with one object per MPPT channel, tagged
with "sort". Channel entities are created on first sight rather than from
configuration, so the same code handles the 1-, 2- and 4-panel variants of this
inverter family without the user telling it which they own.
"""
from __future__ import annotations

import json
import logging
from collections import deque

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CHANNEL_SENSORS,
    CONF_MODEL,
    CONF_SERIAL,
    DEVICE_SENSORS,
    DOMAIN,
    RECENT_MESSAGES,
    SUMMED_DEVICE_FIELDS,
    data_topic,
    describe_fault,
)

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

    # For the diagnostics download: the latest messages as they arrived, and
    # what was made of them.
    recent: deque[dict] = deque(maxlen=RECENT_MESSAGES)

    known_channels: set[int] = set()
    daily: dict[int, DailyYield] = {}
    lifetime: dict[int, float] = {}

    @callback
    def _on_message(msg: mqtt.ReceiveMessage) -> None:
        _LOGGER.debug("message on %s (%d bytes)", msg.topic, len(msg.payload or b""))
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning("Unparseable payload on %s", msg.topic)
            return
        recent.append({"received": dt_util.utcnow().isoformat(), "payload": payload})
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

        # The daily counter can fall back to zero before the day is over, so
        # each channel goes through a DailyYield before summing. The lifetime
        # counter is simply never allowed to fall: "Energy total" is
        # total_increasing, and Home Assistant takes any drop of more than 10%
        # as a meter reset, so one short or zeroed message would make the
        # Energy dashboard count the whole lifetime yield again once the real
        # value returns.
        today = dt_util.now().date()
        for obj in payload:
            ch = int(obj.get("sort", 1))
            if obj.get("genPowerToDay") is not None:
                daily.setdefault(ch, DailyYield()).update(
                    float(obj["genPowerToDay"]), today)
            if obj.get("genPowerTotal") is not None:
                lifetime[ch] = max(lifetime.get(ch, 0.0), float(obj["genPowerTotal"]))

        # Summed over every channel seen (today, for the daily counter), not
        # just this payload, so a channel missing from one message dents neither.
        summed = {
            "genPowerToDay": [d.value for d in daily.values() if d.day == today],
            "genPowerTotal": list(lifetime.values()),
        }

        # The energy counters are per channel and have to be summed; the rest of
        # DEVICE_SENSORS (grid voltage, frequency, rssi, uptime, errCode) genuinely
        # describes the whole inverter and still comes from the first object.
        first = payload[0]
        for key, (field, *_rest) in DEVICE_SENSORS.items():
            if field in SUMMED_DEVICE_FIELDS:
                if summed[field]:
                    entities[key].set_value(round(sum(summed[field]), 3))
            elif field in first:
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

        # A readable fault line covering every channel, so you do not have to
        # know which panel to look at or what a bare integer means.
        faults = [(int(o.get("sort", 1)), o["errCode"])
                  for o in payload if int(o.get("errCode", 0) or 0)]
        ent = entities.get("fault")
        if ent is None:
            ent = EwaySensor(serial, device, "fault", "Fault",
                             None, None, None, "mdi:alert-circle-outline")
            entities["fault"] = ent
            async_add_entities([ent])
        ent.set_value(
            "; ".join(f"panel {ch}: {describe_fault(c)}" for ch, c in faults)
            if faults else "OK"
        )
        if faults:
            # Logged loudly with the raw payload: matching these numbers against
            # whatever the Easy PV app calls them at the same moment is the only
            # route to a real code table, since the vendor publishes none.
            _LOGGER.warning(
                "Eway %s reported a fault: %s (raw: %s)", serial,
                ", ".join(f"panel {ch} code {c}" for ch, c in faults),
                msg.payload[:400],
            )

    hass.data[DOMAIN][entry.entry_id].update(
        messages=recent, daily=daily, lifetime=lifetime, entities=entities)

    unsub = await mqtt.async_subscribe(hass, topic, _on_message)
    entry.async_on_unload(unsub)
    _LOGGER.debug("Subscribed to %s (unsub=%r)", topic, unsub)


class DailyYield:
    """One channel's genPowerToDay, kept from falling back during the day.

    The inverter starts this counter from zero when it powers up at sunrise.
    Some units also send a last message or two with the counter at zero as
    the panel voltage fades at dusk, so "Energy today" read 0 all evening, on
    some inverters of an installation and not on others.

    So within one local calendar day the value only ever rises; the first
    message of a new day starts afresh. A real mid-day reset of the device
    counter cannot be told apart from such a glitch (the payload carries no
    boot counter: "duration" is lifetime operating time, not uptime), so the
    displayed value then holds until the new count overtakes it. That
    under-reports, but never shows a value the day did not reach.
    """

    def __init__(self) -> None:
        self.day = None
        self.value = 0.0

    def update(self, raw: float, today) -> None:
        if today != self.day:
            self.day, self.value = today, raw
        elif raw > self.value:
            self.value = raw


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
