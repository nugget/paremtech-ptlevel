"""Diagnostics for ParemTech PTLevel."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import PTLevelConfigEntry

TO_REDACT = {
    "password",
    "pass",
    "pk",
    "pwd",
    "ssid",
    "tk",
}
"""Payload keys that can carry WiFi credentials or ParemTech session keys.

Firmware 214's JSON carries none of them; they are listed so a future firmware
that adds them cannot leak them through a support download.
"""


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: PTLevelConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    payload = coordinator.client.last_payload
    return {
        "entry": {"data": dict(entry.data), "unique_id": entry.unique_id},
        "last_update_success": coordinator.last_update_success,
        "status": asdict(data.status) if data else None,
        "last_reading": asdict(data.reading) if data and data.reading else None,
        "last_report": data.last_report.isoformat()
        if data and data.last_report
        else None,
        "report_overdue": data.report_overdue(dt_util.utcnow()) if data else None,
        "receiver_payload": async_redact_data(payload, TO_REDACT) if payload else None,
    }
