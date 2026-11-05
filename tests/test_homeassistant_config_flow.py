"""Config flow tests for ParemTech PTLevel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.paremtech_ptlevel.const import DOMAIN
from custom_components.paremtech_ptlevel.ptlevel import (
    PTLevelConnectionError,
    PTLevelUnsupportedError,
)

if TYPE_CHECKING:
    from conftest import FakeReceiver
    from homeassistant.core import HomeAssistant

RECEIVER_ID = "4022D8000001"
pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "receiver")


async def test_user_flow_creates_entry(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """A reachable receiver becomes an entry keyed by its ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: " ptlevel-wellsw-tw.example.test "}
    )

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == f"PTLevel {RECEIVER_ID}"
    assert result.get("data") == {CONF_HOST: "ptlevel-wellsw-tw.example.test"}
    created = result.get("result")
    assert created is not None
    assert created.unique_id == RECEIVER_ID
    assert receiver.hosts[0] == "ptlevel-wellsw-tw.example.test"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PTLevelConnectionError("refused"), "cannot_connect"),
        (PTLevelUnsupportedError("v2 receiver"), "unsupported_receiver"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant,
    receiver: FakeReceiver,
    error: Exception,
    expected: str,
) -> None:
    """Probe failures show an error and let the user try again."""
    receiver.error = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.100"}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {"base": expected}

    receiver.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.100"}
    )
    assert result.get("type") is FlowResultType.CREATE_ENTRY


async def test_user_flow_rejects_known_receiver_and_updates_its_host(
    hass: HomeAssistant,
) -> None:
    """Adding the same receiver again aborts but records its new address."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=RECEIVER_ID, data={CONF_HOST: "192.0.2.50"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.100"}
    )

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "already_configured"
    assert entry.data[CONF_HOST] == "192.0.2.100"


async def test_reconfigure_moves_entry_to_new_address(hass: HomeAssistant) -> None:
    """Reconfiguring to an address that answers as the same receiver succeeds."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=RECEIVER_ID, data={CONF_HOST: "192.0.2.50"}
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result.get("type") is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.100"}
    )

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.0.2.100"


@pytest.mark.parametrize(
    "host",
    [
        "http://192.0.2.100",
        "192.0.2.100:80",
        "192.0.2.100/config",
        "ptlevel wellsw",
        "   ",
    ],
)
async def test_flows_reject_malformed_hosts(
    hass: HomeAssistant, receiver: FakeReceiver, host: str
) -> None:
    """URLs, ports and paths get a field error without probing anything."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: host}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {CONF_HOST: "invalid_host"}

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=RECEIVER_ID, data={CONF_HOST: "192.0.2.50"}
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: host}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {CONF_HOST: "invalid_host"}
    assert receiver.hosts == []


async def test_user_flow_accepts_bracketed_ipv6(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """An IPv6 address may be typed with or without brackets."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "[2001:db8::100]"}
    )

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("data") == {CONF_HOST: "2001:db8::100"}
    assert receiver.hosts[0] == "2001:db8::100"


async def test_reconfigure_refuses_a_different_receiver(
    hass: HomeAssistant, receiver: FakeReceiver
) -> None:
    """An address that answers as another receiver is refused."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="C8C9A3000002", data={CONF_HOST: "192.0.2.101"}
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.100"}
    )

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "wrong_device"
    assert entry.data[CONF_HOST] == "192.0.2.101"
    assert receiver.hosts == ["192.0.2.100"]
