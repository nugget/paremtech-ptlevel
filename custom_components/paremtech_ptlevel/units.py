"""Units the tank forms show and take values in.

Home Assistant converts sensor values for display by itself, but nothing
converts what an owner types into a form: a number field's unit is only a
label. So the forms pick a unit from the Home Assistant unit system and
convert at the edges, while the options always store one unit per quantity
(inches for lengths, US gallons for volumes). Existing settings therefore
need no migration, and the unit system can change at any time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.const import UnitOfLength, UnitOfVolume
from homeassistant.util.unit_conversion import (
    BaseUnitConverter,
    DistanceConverter,
    VolumeConverter,
)
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

if TYPE_CHECKING:
    from homeassistant.util.unit_system import UnitSystem


@dataclass(frozen=True, slots=True)
class FormUnit:
    """A unit the forms show values in, converting to and from the stored unit.

    Attributes:
        unit: The unit shown to the owner.
        decimals: Decimal places the forms show and accept in that unit.
        stored: The unit the options store this quantity in.
        converter: Home Assistant's converter between the two units.
        stored_decimals: Decimal places kept when storing a typed value:
            enough that a value typed in ``unit`` reads back unchanged.
    """

    unit: str
    decimals: int
    stored: str
    converter: type[BaseUnitConverter]
    stored_decimals: int

    @property
    def step(self) -> float:
        """Return the smallest step a form field accepts in this unit."""
        return 10.0**-self.decimals

    def round_stored(self, value: float) -> float:
        """Round a value already in the stored unit for storage."""
        return round(value, self.stored_decimals)

    def to_stored(self, value: float) -> float:
        """Convert a value typed in this unit to the stored unit."""
        return self.round_stored(self.converter.convert(value, self.unit, self.stored))

    def from_stored(self, value: float) -> float:
        """Convert a stored value to this unit, rounded as the forms show it."""
        shown = self.converter.convert(value, self.stored, self.unit)
        return round(shown, self.decimals) + 0.0  # never -0.0

    def format(self, value: float) -> str:
        """Return a stored value as text in this unit, as the forms show it."""
        return f"{self.from_stored(value):.{self.decimals}f}"

    def bounds(self, low: float, high: float) -> tuple[float, float]:
        """Return a range in the stored unit as form bounds in this unit.

        Both ends are rounded inward to the field's step, so any value the
        form accepts stays inside the range.
        """
        scale = 10**self.decimals
        shown_low = self.converter.convert(low, self.stored, self.unit)
        shown_high = self.converter.convert(high, self.stored, self.unit)
        return (
            math.ceil(round(shown_low * scale, 6)) / scale,
            math.floor(round(shown_high * scale, 6)) / scale,
        )


INCHES = FormUnit(UnitOfLength.INCHES, 1, UnitOfLength.INCHES, DistanceConverter, 1)
MILLIMETERS = FormUnit(
    UnitOfLength.MILLIMETERS, 0, UnitOfLength.INCHES, DistanceConverter, 4
)


def length_unit(system: UnitSystem) -> FormUnit:
    """Return the length unit the forms use for a Home Assistant unit system.

    Inches for US customary and millimetres otherwise. Lengths are stored in
    inches. The unit system's own length unit is not used: it is for road
    distances (miles or kilometres).
    """
    return INCHES if system is US_CUSTOMARY_SYSTEM else MILLIMETERS


GALLONS = FormUnit(UnitOfVolume.GALLONS, 0, UnitOfVolume.GALLONS, VolumeConverter, 1)
LITERS = FormUnit(UnitOfVolume.LITERS, 0, UnitOfVolume.GALLONS, VolumeConverter, 4)


def volume_unit(system: UnitSystem) -> FormUnit:
    """Return the volume unit the forms use for a Home Assistant unit system.

    US gallons where the unit system uses gallons, and litres otherwise.
    Volumes are stored in US gallons; Home Assistant has no imperial gallon.
    """
    return GALLONS if system.volume_unit == UnitOfVolume.GALLONS else LITERS
