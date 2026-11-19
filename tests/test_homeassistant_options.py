"""Tank level options and sensors for ParemTech PTLevel."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from conftest import load_payload
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import (
    METRIC_SYSTEM,
    US_CUSTOMARY_SYSTEM,
    UnitSystem,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.paremtech_ptlevel.const import (
    CONF_CAPACITY,
    CONF_DEPTH_OFFSET,
    CONF_FULL_DEPTH,
    CONF_MEASURED_DEPTH,
    DOMAIN,
    SCAN_INTERVAL,
)
from custom_components.paremtech_ptlevel.ptlevel import PTLevelConnectionError
from custom_components.paremtech_ptlevel.sensor import TANK_SENSOR_DESCRIPTIONS
from custom_components.paremtech_ptlevel.tank import TANK_SENSOR_KEYS

if TYPE_CHECKING:
    from conftest import FakeReceiver
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

RECEIVER_ID = "4022D8000001"
START = datetime(2026, 11, 5, 16, 42, tzinfo=UTC)
pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "receiver")
SAVE = {"next_step_id": "calibrate_save"}


def _entry(
    hass: HomeAssistant,
    options: dict[str, Any],
    system: UnitSystem = US_CUSTOMARY_SYSTEM,
) -> MockConfigEntry:
    """Add an entry for the fake receiver, whose reading is 96.19 in."""
    hass.config.units = system
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WELLSW.TW",
        unique_id=RECEIVER_ID,
        data={CONF_HOST: "192.0.2.100"},
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(
    hass: HomeAssistant,
    options: dict[str, Any],
    system: UnitSystem = US_CUSTOMARY_SYSTEM,
) -> MockConfigEntry:
    """Add and load an entry for the fake receiver."""
    entry = _entry(hass, options, system)
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


def _suggested(result: Any) -> dict[str, Any]:
    """Return each field's prefilled value in a shown form."""
    return {
        marker.schema: (marker.description or {}).get("suggested_value")
        for marker in result["data_schema"].schema
    }


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


async def test_clearing_the_offset_removes_both_tank_sensors(
    hass: HomeAssistant,
) -> None:
    """Emptying the depth offset removes both sensors and keeps the full depth."""
    entry = await _setup(hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5})
    assert _registered(hass, "water_depth")

    result = await _open(hass, entry, "tank")
    await _submit(hass, result, {CONF_FULL_DEPTH: 104.5})

    assert entry.options == {CONF_FULL_DEPTH: 104.5}
    assert not _registered(hass, "water_depth")
    assert not _registered(hass, "percent_full")


async def test_full_depth_alone_waits_for_an_offset(hass: HomeAssistant) -> None:
    """Saving only a full depth creates nothing until the tank is calibrated."""
    entry = await _setup(hass, {})

    result = await _open(hass, entry, "tank")
    await _submit(hass, result, {CONF_FULL_DEPTH: 104.5})

    assert entry.options == {CONF_FULL_DEPTH: 104.5}
    assert _state(hass, "water_depth") is None
    assert _state(hass, "percent_full") is None


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, {CONF_DEPTH_OFFSET: None, CONF_FULL_DEPTH: None, CONF_CAPACITY: None}),
        (
            {CONF_FULL_DEPTH: 104.5},
            {CONF_DEPTH_OFFSET: None, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: None},
        ),
        (
            {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: 5000.0},
            {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: 5000.0},
        ),
    ],
)
async def test_tank_form_prefills_saved_settings(
    hass: HomeAssistant, options: dict[str, Any], expected: dict[str, Any]
) -> None:
    """The form starts from the saved settings, so a save keeps what it shows."""
    entry = await _setup(hass, options)

    result = await _open(hass, entry, "tank")

    assert _suggested(result) == expected


def _press(receiver: FakeReceiver, raw: int = 34236) -> None:
    """Have the transmitter send a new report, as its button does."""
    receiver.set_reading(raw, tx_rssi="-118")


@pytest.mark.parametrize("polled", [True, False])
async def test_calibrate_uses_the_report_sent_after_opening(
    hass: HomeAssistant,
    receiver: FakeReceiver,
    freezer: FrozenDateTimeFactory,
    polled: bool,
) -> None:
    """The offset comes from the button's report, confirmed before saving.

    Without a scheduled poll in between, the submission itself reads the
    receiver and finds the report; the clock stays frozen, so the report is
    recognized by its reading, not its time.
    """
    freezer.move_to(START)
    entry = await _setup(
        hass,
        {CONF_DEPTH_OFFSET: 0.0, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: 5000.0},
    )

    result = await _open(hass, entry, "calibrate")
    assert result.get("type") is FlowResultType.FORM
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("water_column") == "96.2"
    assert placeholders.get("reported", "").count(":") == 2

    _press(receiver, 33000)
    if polled:
        freezer.tick(SCAN_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 96.0})

    assert result.get("type") is FlowResultType.MENU
    assert result.get("step_id") == "calibrate_confirm"
    assert result.get("menu_options") == ["calibrate_save", "calibrate"]
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("water_column") == "91.2"
    assert placeholders.get("measured_depth") == "96.0"
    assert placeholders.get("offset") == "4.8"
    assert entry.options == {
        CONF_DEPTH_OFFSET: 0.0,
        CONF_FULL_DEPTH: 104.5,
        CONF_CAPACITY: 5000.0,
    }

    result = await _submit(hass, result, SAVE)

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_DEPTH_OFFSET: 4.8,
        CONF_FULL_DEPTH: 104.5,
        CONF_CAPACITY: 5000.0,
    }
    assert _state(hass, "water_depth") == "96.03"
    assert _state(hass, "percent_full") == "91.9"


async def test_calibrate_refuses_until_the_button_report(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """The report the receiver held when the form opened is never used."""
    entry = await _setup(hass, {})
    result = await _open(hass, entry, "calibrate")
    assert _suggested(result) == {CONF_MEASURED_DEPTH: None}

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 104.5})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "calibrate"
    assert result.get("errors") == {"base": "no_new_report"}
    assert _suggested(result) == {CONF_MEASURED_DEPTH: 104.5}

    _press(receiver)
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 104.5})
    assert result.get("step_id") == "calibrate_confirm"
    assert (result.get("description_placeholders") or {}).get("offset") == "8.3"
    assert entry.options == {}


async def test_calibrate_refuses_an_implausible_depth(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """A depth that would put the chamber far off is refused, then corrected."""
    entry = await _setup(hass, {})
    result = await _open(hass, entry, "calibrate")
    _press(receiver)

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 10.0})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {CONF_MEASURED_DEPTH: "implausible_depth"}

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 100.0})
    assert result.get("step_id") == "calibrate_confirm"
    result = await _submit(hass, result, SAVE)
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEPTH_OFFSET: 3.8}


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        (10376, "0.4"),  # 0.40 in
        (10512, "0.9"),  # 0.95 in: just under the cutoff as displayed
        (10271, "0.0"),  # -0.02 in: no pressure at all
    ],
)
async def test_calibrate_refuses_a_near_zero_report(
    hass: HomeAssistant, receiver: FakeReceiver, raw: int, shown: str
) -> None:
    """A new report under an inch could be a dry chamber or a leak."""
    entry = await _setup(hass, {})
    result = await _open(hass, entry, "calibrate")
    _press(receiver, raw)

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 50.0})

    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {"base": "low_reading"}
    assert (result.get("description_placeholders") or {}).get("water_column") == shown
    assert entry.options == {}


async def test_calibrate_accepts_a_report_shown_as_one_inch(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """A column that rounds to 1.0 in, as the owner sees it, can be calibrated."""
    entry = await _setup(hass, {})
    result = await _open(hass, entry, "calibrate")
    _press(receiver, 10518)  # 0.97 in

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 5.0})

    assert result.get("step_id") == "calibrate_confirm"
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("water_column") == "1.0"
    assert placeholders.get("offset") == "4.0"


@pytest.mark.parametrize("change", ["unloaded", "reloaded"])
async def test_calibrate_stops_if_the_entry_changes_during_the_read(
    hass: HomeAssistant, change: str
) -> None:
    """A read that ends with the entry unloaded or reloaded is not trusted."""
    entry = await _setup(hass, {})
    coordinator = entry.runtime_data

    async def refresh_then_change() -> None:
        if change == "unloaded":
            entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
        else:
            entry.runtime_data = object()

    with patch.object(
        coordinator, "async_refresh", AsyncMock(side_effect=refresh_then_change)
    ):
        result = await _open(hass, entry, "calibrate")

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "not_loaded"
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = coordinator


async def test_calibrate_needs_a_loaded_entry(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """With the receiver unreachable, calibration says so instead of waiting."""
    receiver.error = PTLevelConnectionError("refused")
    entry = _entry(hass, {})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    result = await _open(hass, entry, "calibrate")

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "not_loaded"


async def test_calibrate_stops_when_a_loaded_receiver_stops_answering(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """A loaded entry whose receiver went quiet does not calibrate on old data."""
    entry = await _setup(hass, {})
    receiver.error = PTLevelConnectionError("refused")

    result = await _open(hass, entry, "calibrate")

    assert entry.state is ConfigEntryState.LOADED
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "not_loaded"


async def test_calibrate_keeps_the_press_when_a_read_fails(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """A missed read after the form opened asks for a resubmit, keeping the press."""
    entry = await _setup(hass, {})
    result = await _open(hass, entry, "calibrate")
    _press(receiver)
    receiver.error = PTLevelConnectionError("refused")

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 104.5})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {"base": "cannot_read"}
    assert _suggested(result) == {CONF_MEASURED_DEPTH: 104.5}

    receiver.error = None
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 104.5})
    assert result.get("step_id") == "calibrate_confirm"
    assert entry.options == {}


async def test_calibrate_can_correct_the_depth_without_a_new_press(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """Going back from the confirmation keeps the button report and the depth."""
    entry = await _setup(hass, {})
    result = await _open(hass, entry, "calibrate")
    _press(receiver)
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 104.5})
    assert (result.get("description_placeholders") or {}).get("offset") == "8.3"

    result = await _submit(hass, result, {"next_step_id": "calibrate"})
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {}
    assert _suggested(result) == {CONF_MEASURED_DEPTH: 104.5}

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 105.0})
    assert (result.get("description_placeholders") or {}).get("offset") == "8.8"
    result = await _submit(hass, result, SAVE)
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEPTH_OFFSET: 8.8}


async def test_clearing_settings_offline_still_removes_tank_sensors(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """Clearing the settings while the receiver is unreachable removes the sensors."""
    entry = await _setup(hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5})
    assert _registered(hass, "water_depth")
    receiver.error = PTLevelConnectionError("refused")

    result = await _open(hass, entry, "tank")
    await _submit(hass, result, {})

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.options == {}
    assert not _registered(hass, "water_depth")
    assert not _registered(hass, "percent_full")


def test_tank_sensor_descriptions_match_tank_keys() -> None:
    """The sensor platform describes exactly the sensors tank settings provide."""
    assert {d.key for d in TANK_SENSOR_DESCRIPTIONS} == set(TANK_SENSOR_KEYS)


async def test_calibrate_needs_a_reading(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """With no report seen yet there is nothing to calibrate against."""
    receiver.payload = load_payload("config_after_restart")
    entry = await _setup(hass, {})

    result = await _open(hass, entry, "calibrate")

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "no_reading"


async def test_calibrate_explains_an_unverified_scale(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """Older transmitter hardware reports, but has no water column to calibrate."""
    receiver.payload = dict(load_payload("config_reading"), tx_hardware_version="5")
    entry = await _setup(hass, {})

    result = await _open(hass, entry, "calibrate")

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "unverified_scale"


def _field(result: Any, key: str) -> dict[str, Any]:
    """Return the number-selector config of a shown form's ``key`` field."""
    for marker, selector in result["data_schema"].schema.items():
        if marker.schema == key:
            return selector.config
    raise AssertionError(key)


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        (
            US_CUSTOMARY_SYSTEM,
            {"unit": "in", "bounds": (-24.0, 60.0), "step": 0.1, "saved": (5.2, 104.5)},
        ),
        (
            METRIC_SYSTEM,
            {
                "unit": "mm",
                "bounds": (-609.0, 1524.0),
                "step": 1.0,
                "saved": (132.0, 2654.0),
            },
        ),
    ],
)
async def test_tank_form_uses_the_unit_system(
    hass: HomeAssistant, system: UnitSystem, expected: dict[str, Any]
) -> None:
    """Fields, bounds and saved values are shown in the unit system's unit."""
    entry = await _setup(hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5}, system)

    result = await _open(hass, entry, "tank")

    offset = _field(result, CONF_DEPTH_OFFSET)
    assert offset["unit_of_measurement"] == expected["unit"]
    assert (offset["min"], offset["max"]) == expected["bounds"]
    assert offset["step"] == expected["step"]
    assert _field(result, CONF_FULL_DEPTH)["unit_of_measurement"] == expected["unit"]
    assert _suggested(result) == {
        **dict(
            zip((CONF_DEPTH_OFFSET, CONF_FULL_DEPTH), expected["saved"], strict=True)
        ),
        CONF_CAPACITY: None,
    }
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("unit") == expected["unit"]


async def test_tank_settings_in_millimetres_are_stored_in_inches(
    hass: HomeAssistant,
) -> None:
    """A metric owner types millimetres; the options keep inches."""
    entry = await _setup(hass, {}, METRIC_SYSTEM)

    result = await _open(hass, entry, "tank")
    await _submit(hass, result, {CONF_DEPTH_OFFSET: 132.0, CONF_FULL_DEPTH: 2654.0})

    assert entry.options == {CONF_DEPTH_OFFSET: 5.1969, CONF_FULL_DEPTH: 104.4882}
    assert _state(hass, "percent_full") == "97.0"
    depth = _state(hass, "water_depth")
    assert depth is not None
    assert float(depth) == pytest.approx(101.39 * 25.4)

    result = await _open(hass, entry, "tank")
    assert _suggested(result) == {
        CONF_DEPTH_OFFSET: 132.0,
        CONF_FULL_DEPTH: 2654.0,
        CONF_CAPACITY: None,
    }


async def test_calibrate_in_millimetres(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """Calibration shows and takes millimetres on a metric system."""
    entry = await _setup(hass, {}, METRIC_SYSTEM)

    result = await _open(hass, entry, "calibrate")
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("water_column") == "2443"
    assert placeholders.get("unit") == "mm"
    assert _field(result, CONF_MEASURED_DEPTH)["unit_of_measurement"] == "mm"

    _press(receiver, 33000)  # 91.23 in, 2317 mm
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 2440.0})

    placeholders = result.get("description_placeholders") or {}
    assert result.get("step_id") == "calibrate_confirm"
    assert placeholders.get("water_column") == "2317"
    assert placeholders.get("measured_depth") == "2440"
    assert placeholders.get("offset") == "123"
    assert placeholders.get("unit") == "mm"

    result = await _submit(hass, result, {"next_step_id": "calibrate"})
    assert _suggested(result) == {CONF_MEASURED_DEPTH: 2440.0}

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 2440.0})
    result = await _submit(hass, result, SAVE)
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DEPTH_OFFSET: 4.8349}


@pytest.mark.parametrize(
    ("raw", "outcome", "shown"),
    [
        (10512, "low_reading", "24"),  # 0.95 in shows as 24 mm, under 25 mm
        (10524, None, "25"),  # 1.00 in shows as 25 mm
    ],
)
async def test_low_reading_cutoff_in_millimetres(
    hass: HomeAssistant,
    receiver: FakeReceiver,
    raw: int,
    outcome: str | None,
    shown: str,
) -> None:
    """The cutoff applies to the water column as a metric owner sees it."""
    entry = await _setup(hass, {}, METRIC_SYSTEM)
    result = await _open(hass, entry, "calibrate")
    _press(receiver, raw)

    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 150.0})

    assert (result.get("description_placeholders") or {}).get("water_column") == shown
    if outcome is None:
        assert result.get("step_id") == "calibrate_confirm"
    else:
        assert result.get("errors") == {"base": outcome}


@pytest.mark.parametrize(
    ("system", "unit", "states"),
    [
        (US_CUSTOMARY_SYSTEM, "gal", ("4851.2", "5000.0")),
        (METRIC_SYSTEM, "L", ("18363.8", "18927.1")),
    ],
)
async def test_volume_sensors_use_the_unit_system(
    hass: HomeAssistant, system: UnitSystem, unit: str, states: tuple[str, str]
) -> None:
    """Volumes report natively in the unit system's unit, rounded, unconverted.

    The exact states show the integration rounded in that unit, and the lack
    of a suggested display unit shows Home Assistant had nothing to convert.
    """
    await _setup(
        hass,
        {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: 5000.0},
        system,
    )

    registry = er.async_get(hass)
    for key, expected in zip(("water_volume", "tank_capacity"), states, strict=True):
        entity_id = f"sensor.wellsw_tw_{key}"
        state = hass.states.get(entity_id)
        assert state is not None, key
        assert state.state == expected, key
        assert state.attributes["unit_of_measurement"] == unit
        assert state.attributes["device_class"] == "volume_storage"
        registry_entry = registry.async_get(entity_id)
        assert registry_entry is not None
        assert "sensor.private" not in registry_entry.options, key
    volume_state = hass.states.get("sensor.wellsw_tw_water_volume")
    capacity_state = hass.states.get("sensor.wellsw_tw_tank_capacity")
    assert volume_state is not None
    assert capacity_state is not None
    assert volume_state.attributes["state_class"] == "measurement"
    assert "state_class" not in capacity_state.attributes


async def test_tank_capacity_without_a_water_column(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """Older transmitter hardware has no water column, but capacity still shows."""
    receiver.payload = dict(load_payload("config_reading"), tx_hardware_version="5")
    await _setup(
        hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: 5000.0}
    )

    assert _state(hass, "tank_capacity") == "5000.0"
    for key in ("water_depth", "percent_full", "water_volume"):
        assert _state(hass, key) == STATE_UNAVAILABLE, key


async def test_capacity_without_full_depth_gives_only_tank_capacity(
    hass: HomeAssistant,
) -> None:
    """Volume needs a full depth; capacity alone shows just the capacity."""
    await _setup(hass, {CONF_DEPTH_OFFSET: 5.2, CONF_CAPACITY: 5000.0})

    assert _state(hass, "tank_capacity") == "5000.0"
    assert _state(hass, "water_volume") is None


async def test_clearing_capacity_removes_the_volume_sensors(
    hass: HomeAssistant,
) -> None:
    """Emptying the capacity removes both volume sensors and keeps the rest."""
    entry = await _setup(
        hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5, CONF_CAPACITY: 5000.0}
    )
    assert _registered(hass, "water_volume")

    result = await _open(hass, entry, "tank")
    assert _suggested(result)[CONF_CAPACITY] == 5000.0
    assert _field(result, CONF_CAPACITY)["unit_of_measurement"] == "gal"
    await _submit(hass, result, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5})

    assert entry.options == {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5}
    assert not _registered(hass, "water_volume")
    assert not _registered(hass, "tank_capacity")
    assert _state(hass, "percent_full") == "97.0"


async def test_capacity_in_litres_is_stored_in_gallons(hass: HomeAssistant) -> None:
    """A metric owner types litres; the options keep US gallons."""
    entry = await _setup(
        hass, {CONF_DEPTH_OFFSET: 5.2, CONF_FULL_DEPTH: 104.5}, METRIC_SYSTEM
    )

    result = await _open(hass, entry, "tank")
    assert _field(result, CONF_CAPACITY)["unit_of_measurement"] == "L"
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("volume_unit") == "L"
    await _submit(
        hass,
        result,
        {CONF_DEPTH_OFFSET: 132.0, CONF_FULL_DEPTH: 2654.0, CONF_CAPACITY: 18927.0},
    )

    assert entry.options[CONF_CAPACITY] == 4999.9844
    result = await _open(hass, entry, "tank")
    assert _suggested(result)[CONF_CAPACITY] == 18927.0


async def test_tank_form_saves_unchanged_at_the_range_edges(
    hass: HomeAssistant,
) -> None:
    """Values at the edges of their ranges prefill inside the metric bounds."""
    entry = await _setup(
        hass,
        {CONF_DEPTH_OFFSET: -24.0, CONF_FULL_DEPTH: 1.0, CONF_CAPACITY: 1_000_000.0},
        METRIC_SYSTEM,
    )

    result = await _open(hass, entry, "tank")
    prefilled = _suggested(result)
    assert prefilled == {
        CONF_DEPTH_OFFSET: -609.0,
        CONF_FULL_DEPTH: 26.0,
        CONF_CAPACITY: 3_785_411.0,
    }

    result = await _submit(hass, result, prefilled)

    assert result.get("type") is FlowResultType.CREATE_ENTRY


async def test_unit_system_change_while_a_form_is_open(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """A submission is read in the units its form was shown in."""
    entry = await _setup(hass, {}, METRIC_SYSTEM)

    result = await _open(hass, entry, "tank")
    hass.config.units = US_CUSTOMARY_SYSTEM
    await _submit(hass, result, {CONF_DEPTH_OFFSET: 132.0})
    assert entry.options == {CONF_DEPTH_OFFSET: 5.1969}

    hass.config.units = METRIC_SYSTEM
    result = await _open(hass, entry, "calibrate")
    _press(receiver, 33000)
    hass.config.units = US_CUSTOMARY_SYSTEM
    result = await _submit(hass, result, {CONF_MEASURED_DEPTH: 2440.0})
    placeholders = result.get("description_placeholders") or {}
    assert placeholders.get("offset") == "123"
    assert placeholders.get("unit") == "mm"
    result = await _submit(hass, result, SAVE)
    assert entry.options == {CONF_DEPTH_OFFSET: 4.8349}


async def test_capacity_is_read_in_the_units_its_form_showed(
    hass: HomeAssistant,
) -> None:
    """A capacity typed in litres stays litres if the unit system changes."""
    entry = await _setup(hass, {CONF_DEPTH_OFFSET: 5.2}, METRIC_SYSTEM)

    result = await _open(hass, entry, "tank")
    hass.config.units = US_CUSTOMARY_SYSTEM
    await _submit(hass, result, {CONF_DEPTH_OFFSET: 132.0, CONF_CAPACITY: 18927.0})

    assert entry.options == {CONF_DEPTH_OFFSET: 5.1969, CONF_CAPACITY: 4999.9844}
