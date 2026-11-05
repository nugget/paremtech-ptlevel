"""Brand image checks for ParemTech PTLevel."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "paremtech_ptlevel" / "brand"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_TYPE_RGBA = 6


def _png_header(path: Path) -> tuple[int, int, int]:
    """Return a PNG's width, height and colour type from its IHDR chunk."""
    data = path.read_bytes()[:26]
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise AssertionError(f"{path.name} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height, data[25]


class BrandAssetsTest(unittest.TestCase):
    """Keep the brand images within Home Assistant's brand specification."""

    def test_icons_are_square_transparent_and_sized(self) -> None:
        """Icons are RGBA squares: 256 px, and 512 px for the hDPI version."""
        cases = (
            ("icon.png", 256),
            ("icon@2x.png", 512),
            ("dark_icon.png", 256),
            ("dark_icon@2x.png", 512),
        )
        for name, size in cases:
            with self.subTest(name):
                width, height, color_type = _png_header(BRAND / name)
                self.assertEqual((width, height), (size, size))
                self.assertEqual(color_type, COLOR_TYPE_RGBA)

    def test_logos_are_landscape_transparent_and_sized(self) -> None:
        """Logos are landscape RGBA, 256 px tall, and 512 px for the hDPI version.

        The brands spec allows a shortest side of 128-256 px (256-512 px for
        hDPI) and prefers the maximum.
        """
        cases = (
            ("logo.png", 256),
            ("logo@2x.png", 512),
            ("dark_logo.png", 256),
            ("dark_logo@2x.png", 512),
        )
        for name, shortest in cases:
            with self.subTest(name):
                width, height, color_type = _png_header(BRAND / name)
                self.assertEqual(height, shortest)
                self.assertGreater(width, height)
                self.assertEqual(color_type, COLOR_TYPE_RGBA)

    def test_every_image_has_a_source(self) -> None:
        """Each rendered image comes from an SVG in assets/brand."""
        for png in BRAND.glob("*.png"):
            stem = png.stem.removesuffix("@2x")
            with self.subTest(png.name):
                self.assertTrue(
                    ROOT.joinpath("assets", "brand", f"{stem}.svg").is_file()
                )


if __name__ == "__main__":
    unittest.main()
