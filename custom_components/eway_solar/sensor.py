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
from homeassistant.components.sensor import RestoreSensor, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CHANNEL_SENSORS,
    CONF_MODEL,
    CONF_SERIAL,
    DEVICE_SENSORS,
    DOMAIN,
    OFFLINE_AFTER,
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
        if field in SUMMED_DEVICE_FIELDS:
            entities[key] = EnergySensor(serial, device, key, name, unit, dcl, scl, icon,
                                         daily=field == "genPowerToDay")
        else:
            entities[key] = EwaySensor(serial, device, key, name, unit, dcl, scl, icon)
    async_add_entities(entities.values())

    known_channels: set[int] = set()
    daily: dict[int, DailyYield] = {}
    lifetime: dict[int, float] = {}
    cancel_quiet: CALLBACK_TYPE | None = None

    @callback
    def _went_quiet(_now) -> None:
        nonlocal cancel_quiet
        cancel_quiet = None
        for ent in entities.values():
            ent.went_quiet()

    @callback
    def _on_message(msg: mqtt.ReceiveMessage) -> None:
        nonlocal cancel_quiet
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

        # Every message puts off the point at which the inverter counts as quiet.
        if cancel_quiet is not None:
            cancel_quiet()
        cancel_quiet = async_call_later(hass, OFFLINE_AFTER, _went_quiet)

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

    unsub = await mqtt.async_subscribe(hass, topic, _on_message)
    entry.async_on_unload(unsub)

    @callback
    def _cancel_quiet() -> None:
        if cancel_quiet is not None:
            cancel_quiet()

    entry.async_on_unload(_cancel_quiet)
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
    def went_quiet(self) -> None:
        """The inverter has stopped publishing, which at dusk is all it does.

        Power is then really zero rather than its last reading. The energy
        counters and the operating time keep their value. Everything else is a
        live reading that nothing measures any more, so it becomes unavailable.
        """
        if self.device_class == "power":
            self.set_value(0)
        elif self.state_class != "total_increasing" and self.device_class != "duration":
            self._attr_available = False
            if self.hass is not None:
                self.async_write_ha_state()

    @callback
    def set_value(self, value) -> None:
        self._attr_native_value = value
        self._attr_available = True
        if self.hass is not None:
            self.async_write_ha_state()


class EnergySensor(EwaySensor, RestoreSensor):
    """An energy counter that does not fall within its period, restarts included.

    The per-channel trackers keep the sum from falling while Home Assistant
    runs, but they live in memory and start empty after a restart. The first
    message after one - a dusk zero, or one missing a channel - would then pull
    the value down, and for "Energy total" (total_increasing) a fall is a meter
    reset whose recovery the Energy dashboard counts a second time.

    So the last value is restored and held as a floor: for the rest of its day
    for "Energy today", for good for "Energy total". Should the device's
    lifetime counter ever really start again from zero, the total holds until
    the new count overtakes it. Restoring also means both show their value
    straight after a restart, rather than "unknown" until sunrise.
    """

    def __init__(self, *args, daily: bool) -> None:
        super().__init__(*args)
        self._daily = daily
        self._day = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._attr_native_value is not None:
            return  # a message got here before the restore
        state = await self.async_get_last_state()
        data = await self.async_get_last_sensor_data()
        if state is None or data is None or data.native_value is None:
            return
        day = dt_util.as_local(state.last_updated).date()
        if self._daily and day != dt_util.now().date():
            return  # yesterday's yield is not today's
        self._attr_native_value = data.native_value
        self._day = day

    @callback
    def set_value(self, value) -> None:
        today = dt_util.now().date()
        held = self._attr_native_value
        if (held is not None and float(value) < float(held)
                and (self._day == today or not self._daily)):
            value = held
        self._day = today
        super().set_value(value)
