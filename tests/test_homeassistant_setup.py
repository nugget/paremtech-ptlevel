"""Setup, entity and report-tracking tests for ParemTech PTLevel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from conftest import load_payload
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.paremtech_ptlevel.const import DOMAIN, SCAN_INTERVAL
from custom_components.paremtech_ptlevel.coordinator import storage_key
from custom_components.paremtech_ptlevel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.paremtech_ptlevel.ptlevel import PTLevelConnectionError

if TYPE_CHECKING:
    from conftest import FakeReceiver
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

RECEIVER_ID = "4022D8000001"
START = datetime(2026, 11, 5, 16, 42, tzinfo=UTC)
PREFIX = "wellsw_tw"
pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "receiver")


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return an entry for the fake receiver, titled the way a user would name it."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="WELLSW.TW",
        unique_id=RECEIVER_ID,
        data={CONF_HOST: "192.0.2.100"},
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity: str) -> str:
    """Return the state of ``platform.key`` on the test receiver's device."""
    platform, key = entity.split(".")
    state = hass.states.get(f"{platform}.{PREFIX}_{key}")
    assert state is not None, entity
    return state.state


async def test_setup_creates_device_and_entities(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A receiver with a report populates every enabled entity."""
    freezer.move_to(START)
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor.water_column") == "96.19"
    assert _state(hass, "sensor.battery_voltage") == "6.6"
    assert _state(hass, "sensor.raw_pressure_reading") == "34236"
    assert _state(hass, "sensor.transmitter_signal") == "-119"
    assert _state(hass, "sensor.failed_transmissions") == "0"
    assert _state(hass, "sensor.last_report") == START.isoformat()
    assert _state(hass, "binary_sensor.report_overdue") == STATE_OFF

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, RECEIVER_ID)}
    assert device.name == "WELLSW.TW"
    assert (device.manufacturer, device.model) == ("ParemTech", "PTLevel receiver")
    assert (device.sw_version, device.hw_version) == ("214", "4")
    assert device.configuration_url == "http://192.0.2.100/config"
    assert (dr.CONNECTION_NETWORK_MAC, "40:22:d8:00:00:01") in device.connections

    registry = er.async_get(hass)
    for disabled in ("zero_point", "transmitter_temperature", "wifi_signal"):
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{RECEIVER_ID}_{disabled}"
        )
        assert entity_id is not None, disabled
        registry_entry = registry.async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_receiver_restart_keeps_last_reading(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    receiver: FakeReceiver,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A blank status page after a receiver restart does not erase the reading."""
    freezer.move_to(START)
    await _setup(hass, entry)

    receiver.payload = load_payload("config_after_restart")
    await _poll(hass, freezer)

    assert _state(hass, "sensor.water_column") == "96.19"
    assert _state(hass, "sensor.last_report") == START.isoformat()
    assert _state(hass, "sensor.transmitter_signal") == STATE_UNAVAILABLE


async def test_new_report_moves_last_report(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    receiver: FakeReceiver,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A changed reading counts as a new report; an unchanged one does not."""
    freezer.move_to(START)
    await _setup(hass, entry)

    await _poll(hass, freezer)
    assert _state(hass, "sensor.last_report") == START.isoformat()

    receiver.set_reading(34300, tx_rssi="-121")
    await _poll(hass, freezer)

    assert _state(hass, "sensor.water_column") == "96.45"
    assert _state(hass, "sensor.last_report") == (START + 2 * SCAN_INTERVAL).isoformat()


async def test_report_overdue_after_missed_schedule(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No new report for 13 hours turns the overdue problem on."""
    freezer.move_to(START)
    await _setup(hass, entry)

    freezer.tick(timedelta(hours=12, minutes=58))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _state(hass, "binary_sensor.report_overdue") == STATE_OFF

    await _poll(hass, freezer)
    await _poll(hass, freezer)
    await _poll(hass, freezer)
    assert _state(hass, "binary_sensor.report_overdue") == STATE_ON


async def test_last_report_survives_home_assistant_restart(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    receiver: FakeReceiver,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """The stored report is restored even if the receiver has since restarted."""
    freezer.move_to(START)
    await _setup(hass, entry)
    await _poll(hass, freezer)
    assert hass_storage[storage_key(entry.entry_id)]["data"]["last_report"] == (
        START.isoformat()
    )

    receiver.payload = load_payload("config_after_restart")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, "sensor.water_column") == "96.19"
    assert _state(hass, "sensor.last_report") == START.isoformat()


async def test_removing_entry_deletes_stored_report(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """Removing the entry removes its stored report."""
    freezer.move_to(START)
    await _setup(hass, entry)
    await _poll(hass, freezer)
    assert storage_key(entry.entry_id) in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert storage_key(entry.entry_id) not in hass_storage


@pytest.mark.parametrize(
    "cause",
    ["unreachable", "different receiver"],
)
async def test_setup_retries_when_receiver_is_wrong_or_missing(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    receiver: FakeReceiver,
    cause: str,
) -> None:
    """Setup waits rather than attaching entities to the wrong receiver."""
    if cause == "unreachable":
        receiver.error = PTLevelConnectionError("refused")
    else:
        receiver.payload = dict(load_payload("config_reading"), id="C8C9A3000002")

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    receiver: FakeReceiver,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Diagnostics carry the status and reading, and redact credential keys."""
    freezer.move_to(START)
    receiver.payload = load_payload("config_reading") | {"ssid": "HOME", "pass": "x"}
    await _setup(hass, entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"] == {
        "data": {CONF_HOST: "192.0.2.100"},
        "unique_id": RECEIVER_ID,
    }
    assert diagnostics["status"]["receiver_id"] == RECEIVER_ID
    assert diagnostics["last_reading"]["raw"] == 34236
    assert diagnostics["last_report"] == START.isoformat()
    assert diagnostics["report_overdue"] is False
    assert diagnostics["receiver_payload"]["ssid"] == "**REDACTED**"
    assert diagnostics["receiver_payload"]["pass"] == "**REDACTED**"
    assert diagnostics["receiver_payload"]["fails"] == "0"
