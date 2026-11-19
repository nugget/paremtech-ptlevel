"""Tank level from a PTLevel water column.

The transmitter measures the water column above its chamber's trapped air,
which sits a few inches above the tank floor. Turning that into the tank's
water depth and how full it is needs two numbers only the owner knows: the
depth offset (measured depth minus water column, found by calibrating against
a tape measure) and the depth at which the tank counts as full. Both are kept
in the config entry's options, in inches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .const import CONF_DEPTH_OFFSET, CONF_FULL_DEPTH

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

WATER_DEPTH = "water_depth"
PERCENT_FULL = "percent_full"
TANK_SENSOR_KEYS = (WATER_DEPTH, PERCENT_FULL)
"""Keys of the sensors derived from tank settings, as used in unique IDs."""


@dataclass(frozen=True, slots=True)
class TankSettings:
    """How one tank's water column maps to its depth and fill level.

    Attributes:
        depth_offset: Inches added to the water column to give the water
            depth, roughly the height of the chamber's air pocket above the
            floor. It can be slightly negative when it also absorbs a small
            scale error.
        full_depth: Water depth in inches at 100%, or ``None`` when the owner
            has not set one, in which case there is no percentage.
    """

    depth_offset: float
    full_depth: float | None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> TankSettings | None:
        """Return the tank settings in an entry's options.

        The answer is ``None`` until a depth offset is saved, by calibrating or
        in Tank settings, and again once it is cleared, so an uncalibrated
        tank grows no depth or percentage entities. A full depth saved on its
        own waits for the offset.
        """
        if CONF_DEPTH_OFFSET not in options:
            return None
        full_depth = options.get(CONF_FULL_DEPTH)
        return cls(
            depth_offset=float(options[CONF_DEPTH_OFFSET]),
            full_depth=float(full_depth) if full_depth is not None else None,
        )

    def water_depth(self, water_column: float) -> float:
        """Return the depth of water in the tank, in inches."""
        return water_column + self.depth_offset

    def percent_full(self, water_column: float) -> float | None:
        """Return how full the tank is, as a percentage of the full depth.

        The answer is ``None`` without a full depth. It never goes below zero,
        but can exceed 100 when the water stands above the full mark.
        """
        if self.full_depth is None:
            return None
        return max(0.0, self.water_depth(water_column) / self.full_depth * 100)


def tank_sensor_keys(options: Mapping[str, Any]) -> frozenset[str]:
    """Return the keys of the tank sensors an entry's options provide.

    Water depth needs a depth offset; percent full also needs a full depth.
    Entry setup removes the others from the entity registry, and the sensor
    platform creates exactly these.
    """
    tank = TankSettings.from_options(options)
    if tank is None:
        return frozenset()
    if tank.full_depth is None:
        return frozenset({WATER_DEPTH})
    return frozenset(TANK_SENSOR_KEYS)
