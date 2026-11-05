"""Pytest configuration for ParemTech PTLevel tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.paremtech_ptlevel.ptlevel import (  # noqa: E402
    PTLevelClient,
    ReceiverStatus,
    parse_config_json,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

FIXTURES = Path(__file__).parent / "fixtures"


def load_payload(name: str) -> dict[str, Any]:
    """Return a captured receiver payload from ``tests/fixtures``."""
    return json.loads(FIXTURES.joinpath(f"{name}.json").read_text(encoding="utf-8"))


class FakeReceiver:
    """A receiver whose status page the test controls."""

    def __init__(self) -> None:
        """Start out serving a payload with a transmitter report."""
        self.payload: dict[str, Any] = load_payload("config_reading")
        self.error: Exception | None = None
        self.hosts: list[str] = []

    def set_reading(self, raw: int, *, tx_rssi: str = "-119") -> None:
        """Serve a new transmitter report with pressure ``raw``."""
        self.payload = dict(
            load_payload("config_reading"),
            tx_rssi=tx_rssi,
            tx_sensors=f'[{{"1":{raw},"z":10276}},{{"3":29.4}},{{"2":6.60}}]',
        )

    async def get_status(self, client: PTLevelClient) -> ReceiverStatus:
        """Stand in for :meth:`PTLevelClient.async_get_status`."""
        self.hosts.append(client.host)
        if self.error is not None:
            raise self.error
        client.last_payload = self.payload
        return parse_config_json(self.payload)


@pytest.fixture
def receiver() -> Iterator[FakeReceiver]:
    """Route every PTLevel client request to a fake receiver."""
    fake = FakeReceiver()
    with patch.object(
        PTLevelClient, "async_get_status", autospec=True, side_effect=fake.get_status
    ):
        yield fake
