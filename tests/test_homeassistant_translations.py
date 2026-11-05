"""Translation coverage tests for ParemTech PTLevel."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.paremtech_ptlevel.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
)
from custom_components.paremtech_ptlevel.sensor import SENSOR_DESCRIPTIONS

INTEGRATION = (
    Path(__file__).resolve().parents[1] / "custom_components/paremtech_ptlevel"
)


def _strings() -> dict:
    return json.loads(INTEGRATION.joinpath("strings.json").read_text(encoding="utf-8"))


def test_english_translation_matches_strings() -> None:
    """The shipped English translation is the source strings, unchanged."""
    english = json.loads(
        INTEGRATION.joinpath("translations/en.json").read_text(encoding="utf-8")
    )
    assert english == _strings()


def test_every_entity_has_a_translated_name() -> None:
    """Each description's translation key has a name in strings.json."""
    entity = _strings()["entity"]
    for platform, descriptions in (
        ("sensor", SENSOR_DESCRIPTIONS),
        ("binary_sensor", BINARY_SENSOR_DESCRIPTIONS),
    ):
        names = {key: value["name"] for key, value in entity[platform].items()}
        keys = {description.translation_key for description in descriptions}
        assert keys == set(names), platform


def test_every_enum_state_is_translated() -> None:
    """Each option of an enum sensor has a translated state name."""
    sensors = _strings()["entity"]["sensor"]
    for description in SENSOR_DESCRIPTIONS:
        if description.options is None:
            continue
        states = sensors[description.translation_key]["state"]
        assert set(description.options) == set(states), description.key
