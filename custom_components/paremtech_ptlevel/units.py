"""Lengths and volumes in the tank forms.

Home Assistant converts sensor values for display by itself, but nothing
converts what an owner types into a form: a number field's unit is only a
label. So the forms convert at their boundary. They show lengths in the unit
Home Assistant would show an inch-valued distance sensor in, the same as the
Water depth sensor (millimetres on metric), and volumes in the unit it would
show a US-gallon volume sensor in (litres on metric). The options always store
inches and US gallons, so existing settings need no migration and the unit
system can change at any time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfLength, UnitOfVolume
from homeassistant.util.unit_conversion import DistanceConverter, VolumeConverter

if TYPE_CHECKING:
    from homeassistant.util.unit_system import UnitSystem

FIELD_DECIMALS = 2
"""Decimals kept for a form field's bounds and prefilled value.

Bounds and prefills go through the same rounding, so a value saved at the
edge of its range is never prefilled outside the field's bounds.
"""


def length_unit(system: UnitSystem) -> str:
    """Return the unit the forms show lengths in under ``system``.

    This is the unit Home Assistant converts an inch-valued distance sensor
    to, so the forms match the Water depth sensor; inches when it converts
    nothing (US customary).
    """
    converted = system.get_converted_unit(
        SensorDeviceClass.DISTANCE, UnitOfLength.INCHES
    )
    return converted or UnitOfLength.INCHES


def to_inches(value: float, unit: str) -> float:
    """Convert a length typed in ``unit`` to inches, to a ten-thousandth."""
    return round(DistanceConverter.convert(value, unit, UnitOfLength.INCHES), 4)


def inches_to_field(inches: float, unit: str) -> float:
    """Convert a length in inches to a form field's bound or prefill in ``unit``."""
    converted = DistanceConverter.convert(inches, UnitOfLength.INCHES, unit)
    return round(converted, FIELD_DECIMALS)


def display_decimals(unit: str) -> int:
    """Return the decimals display text shows a length with in ``unit``.

    Whole millimetres; tenths of anything larger, such as inches.
    """
    return 0 if unit == UnitOfLength.MILLIMETERS else 1


def displayed(inches: float, unit: str) -> float:
    """Return a length in inches as display text shows it in ``unit``."""
    converted = DistanceConverter.convert(inches, UnitOfLength.INCHES, unit)
    return round(converted, display_decimals(unit)) + 0.0  # never -0.0


def format_length(inches: float, unit: str) -> str:
    """Return a length in inches as display text in ``unit``."""
    return f"{displayed(inches, unit):.{display_decimals(unit)}f}"


def volume_unit(system: UnitSystem) -> str:
    """Return the unit the forms and volume sensors use for volumes under ``system``.

    This is the unit Home Assistant converts a US-gallon volume sensor to
    (litres on metric); US gallons when it converts nothing. Volumes are
    stored in US gallons: Home Assistant has no imperial gallon.
    """
    converted = system.get_converted_unit(
        SensorDeviceClass.VOLUME, UnitOfVolume.GALLONS
    )
    return converted or UnitOfVolume.GALLONS


def to_gallons(value: float, unit: str) -> float:
    """Convert a volume typed in ``unit`` to US gallons, to a ten-thousandth."""
    return round(VolumeConverter.convert(value, unit, UnitOfVolume.GALLONS), 4)


def gallons_to_field(gallons: float, unit: str) -> float:
    """Convert US gallons to a form field's bound or prefill in ``unit``."""
    converted = VolumeConverter.convert(gallons, UnitOfVolume.GALLONS, unit)
    return round(converted, FIELD_DECIMALS)


def from_gallons(gallons: float, unit: str) -> float:
    """Convert US gallons to ``unit``, to a tenth, for a sensor's state."""
    return round(VolumeConverter.convert(gallons, UnitOfVolume.GALLONS, unit), 1)
