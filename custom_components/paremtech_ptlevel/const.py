"""Constants for ParemTech PTLevel."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "paremtech_ptlevel"
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

MANUFACTURER = "ParemTech"
RECEIVER_MODEL = "PTLevel receiver"

SCAN_INTERVAL = timedelta(seconds=60)
"""How often the receiver is polled. Reading it is cheap and entirely local."""

REPORT_INTERVAL = timedelta(hours=12)
"""ParemTech's default forced-report cadence (30-minute wakes x 24)."""

REPORT_GRACE = timedelta(hours=1)
"""Slack before a missing scheduled report counts as overdue."""

STORAGE_VERSION = 1
