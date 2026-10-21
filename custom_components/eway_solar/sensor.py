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
from homeassistant.util import dt as dt_util

from .const import (
    CHANNEL_SENSORS,
    CONF_MODEL,
    CONF_SERIAL,
    DEVICE_SENSORS,
    DOMAIN,
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

    known_channels: set[int] = set()
    daily: dict[int, DailyYield] = {}

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

        # The daily counter can drop back to zero mid-day when the inverter
        # restarts, so each channel goes through a DailyYield before summing.
        today = dt_util.now().date()
        for obj in payload:
            if obj.get("genPowerToDay") is not None:
                daily.setdefault(int(obj.get("sort", 1)), DailyYield()).update(
                    float(obj["genPowerToDay"]), obj.get("duration"), today)

        # The energy counters are per channel and have to be summed; the rest of
        # DEVICE_SENSORS (grid voltage, frequency, rssi, uptime, errCode) genuinely
        # describes the whole inverter and still comes from the first object.
        first = payload[0]
        for key, (field, *_rest) in DEVICE_SENSORS.items():
            if field == "genPowerToDay":
                # Summed over every channel seen today, not just this payload,
                # so a channel missing from one message does not dent the total.
                values = [d.value for d in daily.values() if d.day == today]
                if values:
                    entities[key].set_value(round(sum(values), 3))
            elif field in SUMMED_DEVICE_FIELDS:
                values = [float(o[field]) for o in payload if o.get(field) is not None]
                if values:
                    entities[key].set_value(round(sum(values), 3))
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

    unsub = await mqtt.async_subscribe(hass, topic, _on_message)
    entry.async_on_unload(unsub)
    _LOGGER.debug("Subscribed to %s (unsub=%r)", topic, unsub)


class DailyYield:
    """One channel's genPowerToDay, kept from falling back during the day.

    The inverter holds this counter in RAM and starts it from zero whenever it
    boots. Normally that is once, at sunrise. But some units restart again as
    the panel voltage fades at dusk and send a last message or two with the
    fresh zero before going dark, so "Energy today" read 0 all evening, on some
    inverters of an installation and not on others.

    A restart shows as the uptime ("duration") going backwards. The yield from
    before it is then carried forward instead of lost, which also covers a
    restart in the middle of a dull day. A lower value WITHOUT a restart is
    treated as a glitch and ignored, because carrying it forward would count
    the same energy twice once the real value comes back. The day boundary is
    the local calendar date: the device has no reset of its own until it next
    boots.
    """

    def __init__(self) -> None:
        self.day = None
        self.offset = 0.0
        self.last = 0.0
        self.uptime: float | None = None

    @property
    def value(self) -> float:
        return self.offset + self.last

    def update(self, raw: float, uptime, today) -> None:
        try:
            uptime = float(uptime)
        except (TypeError, ValueError):
            uptime = None
        if today != self.day:
            self.day, self.offset, self.last = today, 0.0, raw
        elif raw >= self.last:
            self.last = raw
        elif uptime is not None and self.uptime is not None and uptime < self.uptime:
            self.offset += self.last
            self.last = raw
        if uptime is not None:
            self.uptime = uptime


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
