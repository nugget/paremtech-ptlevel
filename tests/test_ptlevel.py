"""Tests for the PTLevel receiver protocol layer."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, cast

import aiohttp

from custom_components.paremtech_ptlevel.ptlevel import (
    COUNTS_PER_INCH_OF_WATER,
    READ_PATHS,
    PTLevelClient,
    PTLevelConnectionError,
    PTLevelUnsupportedError,
    TransmitterReading,
    parse_config_json,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_payload(name: str) -> dict[str, Any]:
    """Return a captured receiver payload."""
    return json.loads(FIXTURES.joinpath(f"{name}.json").read_text(encoding="utf-8"))


class ParseConfigJsonTest(unittest.TestCase):
    """Decode firmware 214 status payloads."""

    def test_reading(self) -> None:
        """A receiver holding a report exposes every transmitter value."""
        status = parse_config_json(load_payload("config_reading"))

        self.assertEqual(status.receiver_id, "4022D8000001")
        self.assertEqual(status.firmware_version, "214")
        self.assertEqual(status.hardware_version, "4")
        self.assertEqual((status.rx_id, status.tx_id), ("208", "147"))
        self.assertEqual((status.wifi_rssi, status.tx_rssi), (-54, -119))
        self.assertEqual(
            (status.tx_firmware_version, status.tx_hardware_version), ("18", "16")
        )
        self.assertEqual(status.failed_transmissions, 0)
        self.assertEqual(
            status.reading,
            TransmitterReading(
                raw=34236, zero=10276, battery_voltage=6.6, cpu_temperature=29.4
            ),
        )

    def test_after_receiver_restart(self) -> None:
        """A restarted receiver has no report, and blanks transmitter fields."""
        status = parse_config_json(load_payload("config_after_restart"))

        self.assertIsNone(status.reading)
        self.assertIsNone(status.tx_rssi)
        self.assertIsNone(status.tx_firmware_version)
        self.assertIsNone(status.tx_hardware_version)
        self.assertEqual(status.wifi_rssi, -54)

    def test_tx_sensors_variants(self) -> None:
        """Sensor objects may come in any order; without a reading there is none."""
        cases = (
            (
                "reordered",
                '[{"2":6.6},{"3":15.1},{"1":10155,"z":10276}]',
                TransmitterReading(10155, 10276, 6.6, 15.1),
            ),
            (
                "no battery or temperature",
                '[{"1":10155,"z":10276}]',
                TransmitterReading(10155, 10276, None, None),
            ),
            ("empty list", "[]", None),
            ("no pressure", '[{"3":15.1},{"2":6.6}]', None),
            ("blank", "  ", None),
        )
        for name, tx_sensors, expected in cases:
            with self.subTest(name):
                payload = dict(load_payload("config_reading"), tx_sensors=tx_sensors)
                self.assertEqual(parse_config_json(payload).reading, expected)

    def test_rejects_unsupported_payloads(self) -> None:
        """Payloads that are not firmware 2xx status pages are refused."""
        reading = load_payload("config_reading")
        cases = (
            ("v3 firmware keys", {"fw_v": "409", "sv": 3, "remotes": []}),
            ("missing id", {k: v for k, v in reading.items() if k != "id"}),
            ("malformed id", dict(reading, id="not-a-mac")),
            ("tx_sensors not JSON", dict(reading, tx_sensors="[{1:2")),
            ("tx_sensors not a list", dict(reading, tx_sensors='{"1":1}')),
            ("raw not a number", dict(reading, tx_sensors='[{"1":"x","z":1}]')),
        )
        for name, payload in cases:
            with (
                self.subTest(name),
                self.assertRaises(PTLevelUnsupportedError),
            ):
                parse_config_json(payload)

    def test_malformed_receiver_numbers_are_unknown(self) -> None:
        """Unparsable signal and counter fields become unknown, not errors."""
        payload = dict(load_payload("config_reading"), rx_rssi="n/a", fails="")
        status = parse_config_json(payload)

        self.assertIsNone(status.wifi_rssi)
        self.assertIsNone(status.failed_transmissions)


class TransmitterReadingTest(unittest.TestCase):
    """Convert raw pressure counts to a water column."""

    def test_water_column(self) -> None:
        """Counts above zero convert at about 249 per inch, and can go negative."""
        cases = (
            ("on the bottom", 34236, 23960, 96.19),
            ("one-foot dip", 13142, 2866, 11.51),
            ("out of the water", 10194, -82, -0.33),
        )
        for name, raw, counts, inches in cases:
            with self.subTest(name):
                reading = TransmitterReading(raw, 10276, None, None)
                self.assertEqual(reading.pressure_counts, counts)
                self.assertAlmostEqual(reading.water_column_inches, inches, places=2)

    def test_scale(self) -> None:
        """One inch of water is about 249 counts."""
        self.assertAlmostEqual(COUNTS_PER_INCH_OF_WATER, 249.09, places=2)


class ClientTest(unittest.IsolatedAsyncioTestCase):
    """Fetch status over HTTP without ever touching an action path."""

    async def test_reads_only_the_status_page(self) -> None:
        """Every request goes to a read-only path."""
        session = FakeSession(text=json.dumps(load_payload("config_reading")))
        client = PTLevelClient(cast("aiohttp.ClientSession", session), "192.0.2.100")

        status = await client.async_get_status()

        self.assertEqual(status.receiver_id, "4022D8000001")
        self.assertEqual(
            [str(url) for url in session.requested],
            ["http://192.0.2.100/config?json=true"],
        )
        self.assertTrue(all(url.path in READ_PATHS for url in session.requested))
        self.assertEqual(client.last_payload, load_payload("config_reading"))

    def test_refuses_action_paths(self) -> None:
        """The client cannot build a URL for the receiver's action paths."""
        client = PTLevelClient(cast("aiohttp.ClientSession", FakeSession()), "host")
        for path in ("/disconnect", "/reset_zero", "/link", "/", "/get_data"):
            with self.subTest(path), self.assertRaises(ValueError):
                client.url(path)

    def test_ipv6_host(self) -> None:
        """IPv6 addresses are bracketed."""
        client = PTLevelClient(
            cast("aiohttp.ClientSession", FakeSession()), "2001:db8::1"
        )
        self.assertEqual(str(client.url()), "http://[2001:db8::1]/config?json=true")

    async def test_failures(self) -> None:
        """Network and protocol failures map to the two error types."""
        cases: tuple[tuple[str, FakeSession, type[Exception]], ...] = (
            ("HTTP error", FakeSession(status=500), PTLevelConnectionError),
            (
                "connection refused",
                FakeSession(error=aiohttp.ClientConnectionError("refused")),
                PTLevelConnectionError,
            ),
            ("timeout", FakeSession(error=TimeoutError()), PTLevelConnectionError),
            (
                "HTML page",
                FakeSession(text="<!DOCTYPE html><title>Your PTLevel</title>"),
                PTLevelUnsupportedError,
            ),
            ("JSON list", FakeSession(text="[]"), PTLevelUnsupportedError),
        )
        for name, session, error in cases:
            with self.subTest(name):
                client = PTLevelClient(cast("aiohttp.ClientSession", session), "host")
                with self.assertRaises(error):
                    await client.async_get_status()


class FakeSession:
    """Just enough of ``aiohttp.ClientSession`` to record GET requests."""

    def __init__(
        self,
        *,
        text: str = "",
        status: int = 200,
        error: Exception | None = None,
    ) -> None:
        """Answer every request with ``text`` and ``status``, or raise ``error``."""
        self.text = text
        self.status = status
        self.error = error
        self.requested: list[Any] = []

    def get(self, url: Any, **_kwargs: Any) -> FakeResponse:
        """Record the URL and return a response context manager."""
        self.requested.append(url)
        return FakeResponse(self)


class FakeResponse:
    """An ``aiohttp`` response context manager backed by a ``FakeSession``."""

    def __init__(self, session: FakeSession) -> None:
        """Answer from ``session``."""
        self._session = session
        self.status = session.status

    async def __aenter__(self) -> FakeResponse:
        """Enter, raising the session's error if it has one."""
        if self._session.error is not None:
            raise self._session.error
        return self

    async def __aexit__(self, *_args: object) -> None:
        """Exit without suppressing errors."""

    async def text(self, **_kwargs: Any) -> str:
        """Return the session's body text."""
        return self._session.text


if __name__ == "__main__":
    unittest.main()
