"""Units the tank forms show and take values in.

Home Assistant converts sensor values for display by itself, but nothing
converts what an owner types into a form: a number field's unit is only a
label. So the forms pick a unit from the Home Assistant unit system, inches
for US customary and millimetres otherwise, and convert at the edges. The
options always store inches, whatever unit the owner sees, so existing
settings need no migration and the unit system can change at any time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.const import UnitOfLength
from homeassistant.util.unit_conversion import DistanceConverter
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

if TYPE_CHECKING:
    from homeassistant.util.unit_system import UnitSystem


@dataclass(frozen=True, slots=True)
class LengthUnit:
    """A length unit the forms show, with conversions to and from stored inches.

    Attributes:
        unit: The unit shown to the owner.
        decimals: Decimal places the forms show and accept in that unit.
    """

    unit: UnitOfLength
    decimals: int

    @property
    def step(self) -> float:
        """Return the smallest step a form field accepts in this unit."""
        return 10.0**-self.decimals

    def round_inches(self, inches: float) -> float:
        """Round a value in inches for storage.

        Inches keep the forms' tenth of an inch. Other units keep four decimal
        places, enough that a value typed in that unit reads back unchanged.
        """
        return round(inches, 1 if self.unit == UnitOfLength.INCHES else 4)

    def to_inches(self, value: float) -> float:
        """Convert a value typed in this unit to inches for storage."""
        inches = DistanceConverter.convert(value, self.unit, UnitOfLength.INCHES)
        return self.round_inches(inches)

    def from_inches(self, inches: float) -> float:
        """Convert stored inches to this unit, rounded as the forms show it."""
        value = DistanceConverter.convert(inches, UnitOfLength.INCHES, self.unit)
        return round(value, self.decimals) + 0.0  # never -0.0

    def format(self, inches: float) -> str:
        """Return stored inches as text in this unit, as the forms show it."""
        return f"{self.from_inches(inches):.{self.decimals}f}"

    def bounds(self, low_inches: float, high_inches: float) -> tuple[float, float]:
        """Return a range in inches as form bounds in this unit.

        Both ends are rounded inward to the field's step, so any value the
        form accepts stays inside the range in inches.
        """
        scale = 10**self.decimals
        low = DistanceConverter.convert(low_inches, UnitOfLength.INCHES, self.unit)
        high = DistanceConverter.convert(high_inches, UnitOfLength.INCHES, self.unit)
        return (
            math.ceil(round(low * scale, 6)) / scale,
            math.floor(round(high * scale, 6)) / scale,
        )


INCHES = LengthUnit(UnitOfLength.INCHES, 1)
MILLIMETERS = LengthUnit(UnitOfLength.MILLIMETERS, 0)


def length_unit(system: UnitSystem) -> LengthUnit:
    """Return the length unit the forms use for a Home Assistant unit system.

    Inches for US customary and millimetres otherwise. The unit system's own
    length unit is not used: it is for road distances (miles or kilometres).
    """
    return INCHES if system is US_CUSTOMARY_SYSTEM else MILLIMETERS
