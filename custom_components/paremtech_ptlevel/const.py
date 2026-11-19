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

CONF_DEPTH_OFFSET = "depth_offset"
"""Option: inches to add to the water column to get the tank's water depth."""

CONF_FULL_DEPTH = "full_depth"
"""Option: the tank's water depth, in inches, when it counts as 100% full."""

CONF_MEASURED_DEPTH = "measured_depth"
"""Calibration input: the water depth the owner just measured, in inches."""

DEPTH_OFFSET_RANGE = (-24.0, 60.0)
"""Plausible depth offsets in inches, from a scale error to a chamber hung high.

A calibration outside this range means the measurement or the reading is
wrong, not that the chamber really sits there.
"""
