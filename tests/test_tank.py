"""Tests for turning a water column into tank depth and fill level."""

from __future__ import annotations

import unittest

from custom_components.paremtech_ptlevel.const import (
    CONF_DEPTH_OFFSET,
    CONF_FULL_DEPTH,
)
from custom_components.paremtech_ptlevel.tank import (
    PERCENT_FULL,
    WATER_DEPTH,
    TankSettings,
    tank_sensor_keys,
)


class TankSettingsFromOptionsTest(unittest.TestCase):
    """Reading tank settings out of an entry's options."""

    def test_sensor_keys(self) -> None:
        """An offset provides water depth; a full depth adds the percentage."""
        cases = [
            ({}, set()),
            ({CONF_FULL_DEPTH: 104.5}, set()),
            ({CONF_DEPTH_OFFSET: 5.2}, {WATER_DEPTH}),
            (
                {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5},
                {WATER_DEPTH, PERCENT_FULL},
            ),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                self.assertEqual(tank_sensor_keys(options), expected)

    def test_options(self) -> None:
        """Only a saved depth offset makes a tank; the full depth is optional."""
        cases = [
            ({}, None),
            ({CONF_FULL_DEPTH: 104.5}, None),
            ({CONF_DEPTH_OFFSET: 5.2}, TankSettings(5.2, None)),
            ({CONF_DEPTH_OFFSET: 0, CONF_FULL_DEPTH: 104}, TankSettings(0.0, 104.0)),
            (
                {CONF_DEPTH_OFFSET: -1.5, CONF_FULL_DEPTH: 104.5},
                TankSettings(-1.5, 104.5),
            ),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                self.assertEqual(TankSettings.from_options(options), expected)


class TankLevelTest(unittest.TestCase):
    """Water depth and percent full from a water column."""

    def test_water_depth_adds_the_offset(self) -> None:
        """Depth is the water column plus the offset, which may be negative."""
        cases = [
            (TankSettings(5.2, None), 99.3, 104.5),
            (TankSettings(0.0, None), 96.19, 96.19),
            (TankSettings(-1.5, None), 50.0, 48.5),
        ]
        for tank, water_column, expected in cases:
            with self.subTest(tank=tank, water_column=water_column):
                self.assertAlmostEqual(tank.water_depth(water_column), expected)

    def test_percent_full(self) -> None:
        """Percent full is depth over full depth, floored at 0, uncapped above."""
        cases = [
            (TankSettings(5.2, 104.5), 99.3, 100.0),
            (TankSettings(4.4, 104.5), 90.6, 95.0 / 104.5 * 100),
            (TankSettings(0.0, 100.0), 50.0, 50.0),
            (TankSettings(0.0, 100.0), 110.0, 110.0),
            (TankSettings(0.0, 100.0), -0.4, 0.0),
            (TankSettings(5.2, None), 99.3, None),
        ]
        for tank, water_column, expected in cases:
            with self.subTest(tank=tank, water_column=water_column):
                percent = tank.percent_full(water_column)
                if expected is None:
                    self.assertIsNone(percent)
                else:
                    assert percent is not None
                    self.assertAlmostEqual(percent, expected)


if __name__ == "__main__":
    unittest.main()
