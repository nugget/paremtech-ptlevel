"""Tank level options and sensors for ParemTech PTLevel."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from conftest import load_payload
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.paremtech_ptlevel.const import (
    CONF_DEPTH_OFFSET,
    CONF_FULL_DEPTH,
    CONF_MEASURED_DEPTH,
    DOMAIN,
)

if TYPE_CHECKING:
    from conftest import FakeReceiver
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

RECEIVER_ID = "4022D8000001"
START = datetime(2026, 11, 5, 16, 42, tzinfo=UTC)
pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "receiver")


async def _setup(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    """Add and load an entry for the fake receiver, whose reading is 96.19 in."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WELLSW.TW",
        unique_id=RECEIVER_ID,
        data={CONF_HOST: "192.0.2.100"},
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, key: str) -> str | None:
    """Return the state of the test receiver's ``sensor.<key>``, if it exists."""
    state = hass.states.get(f"sensor.wellsw_tw_{key}")
    return None if state is None else state.state


def _registered(hass: HomeAssistant, key: str) -> bool:
    """Return whether the entity registry has the receiver's ``key`` sensor."""
    return (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{RECEIVER_ID}_{key}")
        is not None
    )


async def _open(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> Any:
    """Open the options flow and pick ``step`` from its menu."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result.get("type") is FlowResultType.MENU
    assert result.get("menu_options") == ["calibrate", "tank"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def _submit(hass: HomeAssistant, result: Any, data: dict[str, Any]) -> Any:
    """Submit an options form and let the entry reload."""
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    return result


async def test_no_tank_sensors_until_set_up(hass: HomeAssistant) -> None:
    """An entry without tank settings has a water column and nothing derived."""
    await _setup(hass, {})

    assert _state(hass, "water_column") == "96.19"
    assert _state(hass, "water_depth") is None
    assert _state(hass, "percent_full") is None


async def test_tank_settings_add_depth_and_percent(hass: HomeAssistant) -> None:
    """Saving an offset and a full depth adds both tank sensors."""
    entry = await _setup(hass, {})

    result = await _open(hass, entry, "tank")
    assert result.get("type") is FlowResultType.FORM
    result = await _submit(
        hass, result, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5}
    )

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5}
    assert _state(hass, "water_depth") == "101.39"
    assert _state(hass, "percent_full") == "97.0"


async def test_offset_alone_gives_depth_without_percent(hass: HomeAssistant) -> None:
    """Without a full depth there is a water depth but no percentage."""
    await _setup(hass, {CONF_DEPTH_OFFSET: 5.2})

    assert _state(hass, "water_depth") == "101.39"
    assert _state(hass, "percent_full") is None


async def test_clearing_full_depth_removes_percent(hass: HomeAssistant) -> None:
    """Emptying the full depth removes the percentage entity, not just its value."""
    entry = await _setup(hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5})
    assert _registered(hass, "percent_full")

    result = await _open(hass, entry, "tank")
    await _submit(hass, result, {CONF_DEPTH_OFFSET: 5.2})

    assert entry.options == {CONF_DEPTH_OFFSET: 5.2}
    assert not _registered(hass, "percent_full")
    assert _state(hass, "water_depth") == "101.39"


async def test_calibrate_sets_offset_and_keeps_full_depth(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A measured depth becomes the offset against the current water column."""
    freezer.move_to(START)
    entry = await _setup(hass, {CONF_DEPTH_OFFSET: 0.0, CONF_FULL_DEPTH: 104.5})

    result = await _open(hass, entry, "calibrate")
    assert result.get("type") is FlowResultType.FORM
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("water_column") == "96.2"
    assert placeholders.get("reported")

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 104.5})

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEPTH_OFFSET: 8.3, CONF_FULL_DEPTH: 104.5}
    assert _state(hass, "water_depth") == "104.49"
    assert _state(hass, "percent_full") == "100.0"


async def test_calibrate_refuses_an_implausible_depth(hass: HomeAssistant) -> None:
    """A depth that would put the chamber far off is refused, then corrected."""
    entry = await _setup(hass, {})

    result = await _open(hass, entry, "calibrate")
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 10.0})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {CONF_MEASURED_DEPTH: "implausible_depth"}
    assert entry.options == {}

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 100.0})
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEPTH_OFFSET: 3.8}


async def test_calibrate_needs_a_reading(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """With no report seen yet there is nothing to calibrate against."""
    receiver.payload = load_payload("config_after_restart")
    entry = await _setup(hass, {})

    result = await _open(hass, entry, "calibrate")

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "no_reading"
