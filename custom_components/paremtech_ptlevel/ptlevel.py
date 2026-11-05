"""Read-only client for the ParemTech PTLevel receiver's local status API.

The PTLevel Long Range kit pairs a battery transmitter at the tank with a
WiFi receiver indoors. The transmitter reads the air pressure in a weighted
chamber at the bottom of the tank and reports over 915 MHz LoRa, normally
every 12 hours. The receiver relays each report to ParemTech's cloud and also
serves it, unauthenticated, at ``/config?json=true`` on the LAN. That endpoint
is the only thing this module ever requests.

The receiver's other paths are actions triggered by a plain GET, with no
confirmation: ``/disconnect`` drops it off WiFi, ``/reset_zero`` overwrites
the pressure zero point, and ``/link`` starts transmitter pairing. A
monitoring integration must never reach them, so the client builds every URL
from :data:`READ_PATHS` and nothing else.

Supported firmware is the Version 1 receiver's 2xx line (hardware 4,
firmware 214 tested). Version 2 receivers (firmware 4xx) serve a different
API at ``/get_data`` and are rejected with :class:`PTLevelUnsupportedError`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
from yarl import URL

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)

CONFIG_JSON_PATH = "/config"
CONFIG_JSON_QUERY = {"json": "true"}
READ_PATHS = frozenset({CONFIG_JSON_PATH})
"""Every path this client may request. Anything else on the receiver is an action."""

REQUEST_TIMEOUT_SECONDS = 10.0

HPA_PER_COUNT = 0.01
"""Gauge pressure per A/D count, from ParemTech's ``hPa = raw / 100`` formula."""

HPA_PER_INCH_OF_WATER = 2.4909
"""Hydrostatic pressure of one inch of fresh water at about 4 °C."""

COUNTS_PER_INCH_OF_WATER = HPA_PER_INCH_OF_WATER / HPA_PER_COUNT
"""About 249 counts per inch of water above the chamber's trapped air."""

_REQUIRED_KEYS = ("id", "firmware_version", "hardware_version", "tx_sensors")
_RECEIVER_ID_LENGTH = 12


class PTLevelError(Exception):
    """Base error for PTLevel receiver communication."""


class PTLevelConnectionError(PTLevelError):
    """The receiver could not be reached or did not answer in time."""


class PTLevelUnsupportedError(PTLevelError):
    """The receiver answered, but not with a payload this client understands.

    Usually a Version 2 receiver (firmware 4xx), or something other than a
    PTLevel receiver at that address.
    """


@dataclass(frozen=True, slots=True)
class TransmitterReading:
    """One report from the tank transmitter, as cached by the receiver.

    Attributes:
        raw: Pressure sensor A/D reading (sensor ``"1"``).
        zero: Reading with the chamber out of the water (``"z"``).
        battery_voltage: Battery pack voltage; about 7 V is full.
        cpu_temperature: Transmitter CPU temperature in °C. ParemTech
            describes it as uncalibrated, so it is diagnostic only.
    """

    raw: int
    zero: int
    battery_voltage: float | None
    cpu_temperature: float | None

    @property
    def pressure_counts(self) -> int:
        """Return the gauge pressure above the zero point, in A/D counts."""
        return self.raw - self.zero

    @property
    def water_column_inches(self) -> float:
        """Return the water standing above the chamber's air pocket, in inches.

        This is the physical measurement, not the tank level: the chamber's air
        pocket sits a few inches above the tank floor, and the value goes
        slightly negative when there is no pressure at all (chamber out of the
        water, or an air leak in the tubing).
        """
        return self.pressure_counts / COUNTS_PER_INCH_OF_WATER


@dataclass(frozen=True, slots=True)
class ReceiverStatus:
    """A snapshot of the receiver's local status page.

    Attributes:
        receiver_id: The receiver's ID as printed on its label; it is also its
            WiFi MAC address, as 12 upper-case hex digits.
        firmware_version: Receiver firmware, such as ``"214"``.
        hardware_version: Receiver hardware revision, such as ``"4"``.
        rx_id: The receiver's LoRa ID.
        tx_id: The LoRa ID of the transmitter it is paired with.
        wifi_rssi: Receiver WiFi signal strength in dBm.
        tx_rssi: LoRa signal strength of the last transmitter report in dBm.
        tx_firmware_version: Transmitter firmware from the last report.
        tx_hardware_version: Transmitter hardware revision from the last report.
        failed_transmissions: The receiver's count of failed transmitter
            reports. It resets when the receiver restarts.
        reading: The last transmitter report, or ``None`` when the receiver
            holds none. Receivers keep reports only in memory, so this is
            ``None`` after every receiver restart until the next report.
    """

    receiver_id: str
    firmware_version: str
    hardware_version: str
    rx_id: str | None
    tx_id: str | None
    wifi_rssi: int | None
    tx_rssi: int | None
    tx_firmware_version: str | None
    tx_hardware_version: str | None
    failed_transmissions: int | None
    reading: TransmitterReading | None


def parse_config_json(payload: Mapping[str, Any]) -> ReceiverStatus:
    """Parse the ``/config?json=true`` payload from a 2xx-firmware receiver.

    Every value in the payload is a string, and transmitter fields are empty
    strings (``tx_hardware_version`` is ``"0"``) until the receiver has a
    report. ``tx_sensors`` is itself a JSON string holding a list of
    single-key objects in no guaranteed order.

    Raises :class:`PTLevelUnsupportedError` when the payload is missing
    required keys or its transmitter data cannot be decoded.
    """
    missing = [key for key in _REQUIRED_KEYS if key not in payload]
    if missing:
        raise PTLevelUnsupportedError(
            f"receiver payload is missing {', '.join(missing)}"
        )

    receiver_id = str(payload["id"]).strip().upper()
    if len(receiver_id) != _RECEIVER_ID_LENGTH or not all(
        c in "0123456789ABCDEF" for c in receiver_id
    ):
        raise PTLevelUnsupportedError(f"unexpected receiver id {receiver_id!r}")

    tx_hardware = _text(payload.get("tx_hardware_version"))
    return ReceiverStatus(
        receiver_id=receiver_id,
        firmware_version=str(payload["firmware_version"]),
        hardware_version=str(payload["hardware_version"]),
        rx_id=_text(payload.get("rx_id")),
        tx_id=_text(payload.get("tx_id")),
        wifi_rssi=_int(payload.get("rx_rssi")),
        tx_rssi=_int(payload.get("tx_rssi")),
        tx_firmware_version=_text(payload.get("tx_firmware_version")),
        tx_hardware_version=None if tx_hardware == "0" else tx_hardware,
        failed_transmissions=_int(payload.get("fails")),
        reading=_parse_tx_sensors(payload["tx_sensors"]),
    )


class PTLevelClient:
    """Fetch status from one PTLevel receiver.

    The client never opens its own session: pass Home Assistant's shared
    ``aiohttp`` session so connections are pooled and closed by core.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize a client for the receiver at ``host``.

        ``timeout`` is the number of seconds to wait for the whole response.
        """
        self._session = session
        self.host = host
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self.last_payload: dict[str, Any] | None = None

    def url(self, path: str = CONFIG_JSON_PATH) -> URL:
        """Return the URL for a read-only receiver path, bracketing IPv6 hosts.

        Raises ``ValueError`` for any ``path`` not in :data:`READ_PATHS`, so an
        action path can never be requested by mistake.
        """
        if path not in READ_PATHS:
            raise ValueError(f"{path} is not a read-only PTLevel receiver path")
        return URL.build(
            scheme="http", host=self.host, path=path, query=CONFIG_JSON_QUERY
        )

    async def async_get_status(self) -> ReceiverStatus:
        """Read and parse the receiver's status.

        Raises :class:`PTLevelConnectionError` when the receiver does not
        answer or answers with an HTTP error, and
        :class:`PTLevelUnsupportedError` when the answer is not a
        2xx-firmware status payload.
        """
        url = self.url()
        try:
            async with self._session.get(url, timeout=self._timeout) as response:
                if response.status != 200:  # noqa: PLR2004
                    raise PTLevelConnectionError(
                        f"{self.host} answered HTTP {response.status}"
                    )
                text = await response.text(errors="replace")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PTLevelConnectionError(f"cannot reach {self.host}: {err}") from err

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as err:
            raise PTLevelUnsupportedError(
                f"{self.host} did not answer with JSON; it may be a Version 2 "
                "receiver, which this integration does not support yet"
            ) from err
        if not isinstance(payload, dict):
            raise PTLevelUnsupportedError(f"{self.host} answered with a non-object")

        _LOGGER.debug("PTLevel receiver %s status: %s", self.host, payload)
        self.last_payload = payload
        return parse_config_json(payload)


def _parse_tx_sensors(value: Any) -> TransmitterReading | None:
    """Decode the ``tx_sensors`` string, or return ``None`` when it is empty."""
    text = _text(value)
    if text is None:
        return None
    try:
        items = json.loads(text)
    except json.JSONDecodeError as err:
        raise PTLevelUnsupportedError(f"cannot decode tx_sensors {text!r}") from err
    if not isinstance(items, list):
        raise PTLevelUnsupportedError(f"tx_sensors is not a list: {text!r}")

    sensors: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            sensors.update(item)
    if "1" not in sensors or "z" not in sensors:
        return None

    try:
        return TransmitterReading(
            raw=int(sensors["1"]),
            zero=int(sensors["z"]),
            battery_voltage=_float(sensors.get("2")),
            cpu_temperature=_float(sensors.get("3")),
        )
    except (TypeError, ValueError) as err:
        raise PTLevelUnsupportedError(f"cannot decode tx_sensors {text!r}") from err


def _text(value: Any) -> str | None:
    """Return a stripped string, or ``None`` for missing and empty values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    """Return an integer, or ``None`` for missing, empty or malformed values."""
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    """Return a float, or ``None`` for missing, empty or malformed values."""
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None
