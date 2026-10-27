"""Diagnostics download: the latest raw messages and what was made of them.

Matching what the inverter sent against what the sensors show is how the
dusk zero (#3) was told apart from a bug, and until now it took a broker log.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL, DOMAIN

# Nothing in a bug report needs the serial; it is the device's identity on the
# vendor cloud. The payload itself does not carry it.
TO_REDACT = {CONF_SERIAL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    runtime = hass.data[DOMAIN].get(entry.entry_id, {})
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "recent_messages": list(runtime.get("messages", [])),
        "energy_today_per_channel": {
            ch: {"day": str(d.day), "value": d.value}
            for ch, d in runtime.get("daily", {}).items()
        },
        "energy_total_per_channel": dict(runtime.get("lifetime", {})),
        "sensors": {
            key: ent.native_value for key, ent in runtime.get("entities", {}).items()
        },
    }
