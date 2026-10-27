"""Constants for the Eway solar micro-inverter integration."""
from datetime import timedelta

DOMAIN = "eway_solar"

CONF_MODEL = "model"
CONF_SERIAL = "serial"

# The inverter publishes to /<model>/<serial>/data/post. Both parts are visible
# in the Easy PV app under Equipment Details, but the config flow discovers them
# from the wildcard below so nobody has to type them.
# NB the LEADING SLASH is significant. The device publishes to
# "/<model>/<serial>/data/post", which MQTT treats as five levels with an empty
# first one, so "+/+/data/post" (four levels) never matches. Caught only by
# testing against a real inverter.
# manifest.json subscribes to the same topic for MQTT discovery.
DISCOVERY_TOPIC = "/+/+/data/post"


def data_topic(model: str, serial: str) -> str:
    return f"/{model}/{serial}/data/post"


# The inverter publishes about once a minute while the panels deliver, and at
# dusk it simply stops, with no last message to say so. After this long
# without one it is taken to have gone quiet.
OFFLINE_AFTER = timedelta(minutes=10)


# Per-MPPT-channel measurements. The device reports one JSON object per channel
# in a list, tagged with "sort".
#   key: (json field, name suffix, unit, device_class, state_class, icon)
CHANNEL_SENSORS = {
    "power": ("genPower", "power", "W", "power", "measurement", None),
    "voltage": ("inputVoltage", "voltage", "V", "voltage", "measurement", None),
    # NB the firmware capitalises this one differently to every other field.
    "current": ("InputCurrent", "current", "A", "current", "measurement", None),
    "temperature": ("temperature", "temperature", "°C", "temperature", "measurement", None),
    # errCode is reported per channel, not once for the inverter, so a fault on
    # one panel alone is invisible if you only read the first object.
    "error_code": ("errCode", "error code", None, None, None, "mdi:alert-circle-outline"),
}


def describe_fault(code) -> str:
    """Render errCode readably WITHOUT inventing meanings for the numbers.

    EasyCharging publish no code table. The VN2T08EU/VN2T10EU/VN2T06EU manual
    documents only LED flash patterns (green = exporting normally; red
    short-short-long = recoverable warning; red long-short-short = probable
    hardware fault), and the Easy PV app fetches its alarm text from the vendor
    cloud rather than holding it locally.

    So 0 is the only value whose meaning is certain - the inverter reports it
    continuously while exporting normally. Everything else is shown verbatim and
    labelled as unmapped, because a plausible-looking wrong translation of a
    fault code is worse than no translation at all.
    """
    try:
        code = int(code)
    except (TypeError, ValueError):
        return f"Unknown ({code!r})"
    if code == 0:
        return "OK"
    return f"Fault code {code} (meaning not published by the vendor)"

# Whole-inverter measurements, taken from the first channel object since they
# describe the AC side or the device as a whole.
DEVICE_SENSORS = {
    "grid_voltage": ("gridVoltage", "Grid voltage", "V", "voltage", "measurement", None),
    "grid_frequency": ("gridFreq", "Grid frequency", "Hz", "frequency", "measurement", None),
    "energy_today": ("genPowerToDay", "Energy today", "Wh", "energy", "total_increasing", None),
    "energy_total": ("genPowerTotal", "Energy total", "kWh", "energy", "total_increasing", None),
    "wifi_signal": ("rssi", "WiFi signal", "dBm", "signal_strength", "measurement", None),
    "uptime": ("duration", "Uptime", "s", "duration", "measurement", None),
    "error_code": ("errCode", "Error code", None, None, None, "mdi:alert-circle-outline"),
}

# These two look device-wide but are reported PER MPPT CHANNEL, so they have to be
# added up. Measured on a 2-panel VN2T08EU-016212C: channel 1 reported 1853 Wh /
# 199.8 kWh while channel 2 simultaneously reported 1431 Wh / 164.457 kWh, and the
# gap widens over time as the panels are not identically oriented. Reading either
# channel alone silently loses most of the other one - the figures stay plausible,
# they are just too low, which is the worst way for it to be wrong.
# Everything else in DEVICE_SENSORS really is identical across channels.
SUMMED_DEVICE_FIELDS = {"genPowerToDay", "genPowerTotal"}
