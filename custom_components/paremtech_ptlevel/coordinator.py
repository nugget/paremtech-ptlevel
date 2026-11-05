"""Data coordinator for ParemTech PTLevel.

The receiver's status page carries no timestamp, and the transmitter normally
reports only twice a day, so freshness has to be inferred. The coordinator
treats a change in the reading's signature (pressure, zero point, battery,
CPU temperature and LoRa signal) as a new report and stamps it with the time
it was first seen. Two reports with identical values are therefore counted as
one; in practice the LoRa signal and CPU temperature differ on every report.

Receivers hold reports only in memory, so a receiver restart blanks its page
until the next report, up to 12 hours later. The coordinator keeps the last
reading it saw, with its timestamp, in Home Assistant storage, so neither a
receiver restart nor a Home Assistant restart loses it. A report that arrives
while Home Assistant is down is stamped when Home Assistant next sees it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, REPORT_GRACE, REPORT_INTERVAL, SCAN_INTERVAL, STORAGE_VERSION
from .ptlevel import (
    PTLevelClient,
    PTLevelError,
    ReceiverStatus,
    TransmitterReading,
)

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

type ReportSignature = tuple[int, int, float | None, float | None, int | None]


@dataclass(frozen=True, slots=True)
class PTLevelData:
    """One coordinator snapshot.

    Attributes:
        status: The receiver's status from the latest poll.
        reading: The last transmitter report seen, which survives receiver and
            Home Assistant restarts. ``None`` until a report has been seen.
        last_report: When this integration first saw ``reading``.
    """

    status: ReceiverStatus
    reading: TransmitterReading | None
    last_report: datetime | None

    def report_overdue(self, now: datetime) -> bool | None:
        """Return whether the transmitter has missed its scheduled report.

        ``now`` must be timezone-aware. The answer is ``None`` until a report
        has been seen, and otherwise whether more than the report interval
        plus grace has passed since the last one.
        """
        if self.last_report is None:
            return None
        return now - self.last_report > REPORT_INTERVAL + REPORT_GRACE


class PTLevelCoordinator(DataUpdateCoordinator[PTLevelData]):
    """Poll one receiver and track transmitter reports."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: PTLevelClient
    ) -> None:
        """Initialize the coordinator for the receiver ``client`` reads."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._signature: ReportSignature | None = None
        self._reading: TransmitterReading | None = None
        self._last_report: datetime | None = None

    async def _async_setup(self) -> None:
        """Restore the last report seen before Home Assistant restarted."""
        stored = await self._store.async_load()
        if not stored:
            return
        try:
            self._reading = TransmitterReading(**stored["reading"])
            self._signature = _signature(self._reading, stored["tx_rssi"])
            self._last_report = dt_util.parse_datetime(stored["last_report"])
        except KeyError, TypeError, ValueError:
            _LOGGER.warning(
                "Ignoring unreadable stored PTLevel report for %s",
                self.config_entry.title,
            )
            self._signature = self._reading = self._last_report = None

    async def _async_update_data(self) -> PTLevelData:
        """Poll the receiver and fold in any new transmitter report."""
        try:
            status = await self.client.async_get_status()
        except PTLevelError as err:
            raise UpdateFailed(str(err)) from err

        expected_id = self.config_entry.unique_id
        if expected_id is not None and status.receiver_id != expected_id:
            raise UpdateFailed(
                f"{self.client.host} now answers as receiver {status.receiver_id}, "
                f"not {expected_id}; reconfigure the entry with the right address"
            )

        if status.reading is not None:
            signature = _signature(status.reading, status.tx_rssi)
            if signature != self._signature:
                self._signature = signature
                self._reading = status.reading
                self._last_report = dt_util.utcnow()
                self._store.async_delay_save(self._stored_report, 1)
                _LOGGER.debug(
                    "New PTLevel report from %s: %s",
                    self.config_entry.title,
                    status.reading,
                )

        return PTLevelData(
            status=status, reading=self._reading, last_report=self._last_report
        )

    def _stored_report(self) -> dict[str, Any]:
        """Return the last report in its storage form."""
        if self._reading is None or self._last_report is None:
            return {}
        return {
            "reading": asdict(self._reading),
            "tx_rssi": self._signature[4] if self._signature else None,
            "last_report": self._last_report.isoformat(),
        }


def storage_key(entry_id: str) -> str:
    """Return the storage key holding a config entry's last report."""
    return f"{DOMAIN}.{entry_id}"


def _signature(reading: TransmitterReading, tx_rssi: int | None) -> ReportSignature:
    """Return the values that change from one transmitter report to the next."""
    return (
        reading.raw,
        reading.zero,
        reading.battery_voltage,
        reading.cpu_temperature,
        tx_rssi,
    )
