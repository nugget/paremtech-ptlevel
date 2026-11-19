"""Tests for the lengths the tank forms show and take."""

from __future__ import annotations

import unittest

from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

from custom_components.paremtech_ptlevel.units import (
    format_length,
    from_gallons,
    gallons_to_field,
    inches_to_field,
    length_unit,
    to_gallons,
    to_inches,
    volume_unit,
)


class LengthTest(unittest.TestCase):
    """Converting between the shown unit and stored inches."""

    def test_unit_follows_home_assistant(self) -> None:
        """The forms use the unit Home Assistant shows an inch sensor in."""
        self.assertEqual(length_unit(US_CUSTOMARY_SYSTEM), "in")
        self.assertEqual(length_unit(METRIC_SYSTEM), "mm")

    def test_typed_lengths_are_stored_in_inches(self) -> None:
        """Inches are stored as typed; other units to a ten-thousandth of an inch."""
        cases = [
            ("in", 104.5, 104.5),
            ("in", 5.24, 5.24),
            ("mm", 1500, 59.0551),
            ("mm", 132, 5.1969),
            ("mm", -609.6, -24.0),
        ]
        for unit, typed, stored in cases:
            with self.subTest(unit=unit, typed=typed):
                self.assertEqual(to_inches(typed, unit), stored)

    def test_fields_keep_two_decimals(self) -> None:
        """Bounds and prefills keep fractions, so stored values round-trip."""
        cases = [
            ("in", 5.2, 5.2),
            ("mm", 5.2, 132.08),
            ("mm", 5.1969, 132.0),
            ("mm", -24.0, -609.6),
            ("mm", 600.0, 15240.0),
        ]
        for unit, inches, shown in cases:
            with self.subTest(unit=unit, inches=inches):
                self.assertEqual(inches_to_field(inches, unit), shown)

    def test_display_text_rounds_per_unit(self) -> None:
        """Whole millimetres, tenths of an inch, and never a minus zero."""
        cases = [
            ("in", 104.5, "104.5"),
            ("in", 4.7719, "4.8"),
            ("mm", 5.2, "132"),
            ("mm", -0.01, "0"),
        ]
        for unit, inches, text in cases:
            with self.subTest(unit=unit, inches=inches):
                self.assertEqual(format_length(inches, unit), text)


class VolumeTest(unittest.TestCase):
    """Converting between the shown volume unit and stored US gallons."""

    def test_unit_follows_home_assistant(self) -> None:
        """The forms and sensors use the unit Home Assistant shows gallons in."""
        self.assertEqual(volume_unit(US_CUSTOMARY_SYSTEM), "gal")
        self.assertEqual(volume_unit(METRIC_SYSTEM), "L")

    def test_round_trips(self) -> None:
        """A typed capacity is stored in gallons and prefills as typed."""
        cases = [
            ("gal", 5000, 5000.0, 5000.0),
            ("L", 18927, 4999.9844, 18927.0),
        ]
        for unit, typed, stored, prefill in cases:
            with self.subTest(unit=unit, typed=typed):
                self.assertEqual(to_gallons(typed, unit), stored)
                self.assertEqual(gallons_to_field(stored, unit), prefill)

    def test_sensor_states_round_to_a_tenth(self) -> None:
        """Sensor states are clean numbers in the shown unit."""
        self.assertEqual(from_gallons(5000.0, "gal"), 5000.0)
        self.assertEqual(from_gallons(5000.0, "L"), 18927.1)


if __name__ == "__main__":
    unittest.main()
