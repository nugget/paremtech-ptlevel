"""Tests for the units the tank forms show and take values in."""

from __future__ import annotations

import unittest

from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

from custom_components.paremtech_ptlevel.units import (
    GALLONS,
    INCHES,
    LITERS,
    MILLIMETERS,
    length_unit,
    volume_unit,
)


class FormUnitTest(unittest.TestCase):
    """Converting between the shown unit and stored inches."""

    def test_unit_follows_the_unit_system(self) -> None:
        """US customary shows inches; anything else shows millimetres."""
        self.assertIs(length_unit(US_CUSTOMARY_SYSTEM), INCHES)
        self.assertIs(length_unit(METRIC_SYSTEM), MILLIMETERS)

    def test_typed_values_are_stored_in_inches(self) -> None:
        """Inches keep a tenth; millimetres keep enough to read back unchanged."""
        cases = [
            (INCHES, 104.5, 104.5),
            (INCHES, 5.24, 5.2),
            (MILLIMETERS, 1500, 59.0551),
            (MILLIMETERS, 132, 5.1969),
            (MILLIMETERS, -610, -24.0157),
        ]
        for unit, typed, stored in cases:
            with self.subTest(unit=unit.unit, typed=typed):
                self.assertEqual(unit.to_stored(typed), stored)

    def test_stored_inches_read_back_in_the_shown_unit(self) -> None:
        """A value typed in millimetres comes back as typed after storage."""
        cases = [
            (INCHES, 104.5, 104.5, "104.5"),
            (MILLIMETERS, 59.0551, 1500.0, "1500"),
            (MILLIMETERS, 5.2, 132.0, "132"),
            (MILLIMETERS, -0.01, 0.0, "0"),
        ]
        for unit, inches, shown, text in cases:
            with self.subTest(unit=unit.unit, inches=inches):
                self.assertEqual(unit.from_stored(inches), shown)
                self.assertEqual(unit.format(inches), text)

    def test_bounds_round_inward_to_the_step(self) -> None:
        """Converted form bounds never let a value outside the range in inches."""
        cases = [
            (INCHES, (-24.0, 60.0), (-24.0, 60.0)),
            (INCHES, (1.0, 600.0), (1.0, 600.0)),
            (MILLIMETERS, (-24.0, 60.0), (-609.0, 1524.0)),
            (MILLIMETERS, (1.0, 600.0), (26.0, 15240.0)),
            (MILLIMETERS, (0.0, 600.0), (0.0, 15240.0)),
        ]
        for unit, inches, expected in cases:
            with self.subTest(unit=unit.unit, inches=inches):
                self.assertEqual(unit.bounds(*inches), expected)

    def test_step_matches_the_shown_decimals(self) -> None:
        """A tenth of an inch, or a whole millimetre."""
        self.assertEqual(INCHES.step, 0.1)
        self.assertEqual(MILLIMETERS.step, 1.0)


class VolumeUnitTest(unittest.TestCase):
    """Converting between the shown volume unit and stored US gallons."""

    def test_unit_follows_the_unit_system(self) -> None:
        """Gallons where the unit system uses them; litres otherwise."""
        self.assertIs(volume_unit(US_CUSTOMARY_SYSTEM), GALLONS)
        self.assertIs(volume_unit(METRIC_SYSTEM), LITERS)

    def test_round_trips(self) -> None:
        """A typed capacity is stored in gallons and reads back as typed."""
        cases = [
            (GALLONS, 5000, 5000.0, "5000"),
            (LITERS, 18927, 4999.9844, "18927"),
        ]
        for unit, typed, stored, text in cases:
            with self.subTest(unit=unit.unit, typed=typed):
                self.assertEqual(unit.to_stored(typed), stored)
                self.assertEqual(unit.from_stored(stored), float(typed))
                self.assertEqual(unit.format(stored), text)

    def test_bounds(self) -> None:
        """Capacity bounds in gallons convert to whole litres, rounded inward."""
        self.assertEqual(GALLONS.bounds(1.0, 1_000_000.0), (1.0, 1_000_000.0))
        self.assertEqual(LITERS.bounds(1.0, 1_000_000.0), (4.0, 3_785_411.0))


if __name__ == "__main__":
    unittest.main()
