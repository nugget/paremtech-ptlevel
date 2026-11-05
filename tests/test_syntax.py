"""Syntax checks for integration Python files."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SyntaxTest(unittest.TestCase):
    """Parse Python files without importing Home Assistant."""

    def test_python_files_parse(self) -> None:
        """All project Python files should be syntactically valid."""
        paths = sorted(
            [
                *ROOT.joinpath("custom_components").rglob("*.py"),
                *ROOT.joinpath("tests").rglob("*.py"),
            ]
        )

        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
