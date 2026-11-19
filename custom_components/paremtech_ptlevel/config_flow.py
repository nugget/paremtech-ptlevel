"""Config flow for ParemTech PTLevel."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, OptionsFlowWithReload
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from homeassistant.util import dt as dt_util
from yarl import URL

from .const import (
    CONF_CAPACITY,
    CONF_DEPTH_OFFSET,
    CONF_FULL_DEPTH,
    CONF_MEASURED_DEPTH,
    DEPTH_OFFSET_RANGE,
    DOMAIN,
    MIN_CALIBRATION_WATER_COLUMN,
)
from .ptlevel import (
    PTLevelClient,
    PTLevelConnectionError,
    PTLevelUnsupportedError,
    ReceiverStatus,
)
from .units import FormUnit, length_unit, volume_unit

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.util.unit_system import UnitSystem

    from .coordinator import PTLevelCoordinator, PTLevelData
    from .ptlevel import TransmitterReading

_LOGGER = logging.getLogger(__name__)

MAX_DEPTH = 600.0
"""Deepest water depth the forms accept, in inches (50 ft)."""

MAX_CAPACITY = 1_000_000.0
"""Largest tank capacity the forms accept, in US gallons."""


def _tank_units(system: UnitSystem) -> dict[str, FormUnit]:
    """Return the unit each tank setting is shown in for a unit system.

    Lengths are stored in inches and the capacity in US gallons (see
    ``units.py``).
    """
    length = length_unit(system)
    return {
        CONF_DEPTH_OFFSET: length,
        CONF_FULL_DEPTH: length,
        CONF_CAPACITY: volume_unit(system),
    }


def _unit_field(units: FormUnit, low: float, high: float) -> NumberSelector:
    """Return a typed-in number field in the owner's unit.

    ``low`` and ``high`` are in the stored unit, as the options keep them.
    """
    low, high = units.bounds(low, high)
    return NumberSelector(
        NumberSelectorConfig(
            min=low,
            max=high,
            step=units.step,
            unit_of_measurement=units.unit,
            mode=NumberSelectorMode.BOX,
        )
    )


def _tank_schema(units: dict[str, FormUnit]) -> probatio.Schema:
    """Return the tank settings form, in the owner's units.

    Every setting is optional, and an empty field removes its option. The
    depth offset deliberately has no default: an owner who opens the form
    only to set the full depth must not end up with an uncalibrated offset of
    zero, which would create a Water depth that is really the water column.
    """
    return probatio.Schema(
        {
            probatio.Optional(CONF_DEPTH_OFFSET): _unit_field(
                units[CONF_DEPTH_OFFSET], *DEPTH_OFFSET_RANGE
            ),
            probatio.Optional(CONF_FULL_DEPTH): _unit_field(
                units[CONF_FULL_DEPTH], 1.0, MAX_DEPTH
            ),
            probatio.Optional(CONF_CAPACITY): _unit_field(
                units[CONF_CAPACITY], 1.0, MAX_CAPACITY
            ),
        }
    )


def _calibrate_schema(units: FormUnit) -> probatio.Schema:
    """Return the calibrate form, taking the measured depth in the owner's unit."""
    return probatio.Schema(
        {probatio.Required(CONF_MEASURED_DEPTH): _unit_field(units, 0.0, MAX_DEPTH)}
    )


class PTLevelConfigFlow(  # pyright: ignore[reportGeneralTypeIssues]
    config_entries.ConfigFlow,
    domain=DOMAIN,  # pyright: ignore[reportCallIssue]
):
    """Add a PTLevel receiver by its hostname or IP address.

    Receivers do not advertise themselves on the network, so there is no
    discovery step. The receiver's ID (its MAC address) is the entry's unique
    ID, so the same receiver cannot be added twice under different addresses.
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PTLevelOptionsFlow:  # noqa: ARG004
        """Return the flow that sets up the tank's depth and fill level."""
        return PTLevelOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the receiver's address and validate it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = _normalize_host(user_input[CONF_HOST])
            if host is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_schema(user_input),
                    errors={CONF_HOST: "invalid_host"},
                )
            status, error = await self._async_probe(host)
            if status is not None:
                await self.async_set_unique_id(status.receiver_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=f"PTLevel {status.receiver_id}",
                    data={CONF_HOST: host},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move an existing entry to a new address for the same receiver."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = _normalize_host(user_input[CONF_HOST])
            if host is None:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_schema(user_input),
                    errors={CONF_HOST: "invalid_host"},
                )
            status, error = await self._async_probe(host)
            if status is not None:
                await self.async_set_unique_id(status.receiver_id)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    async def _async_probe(self, host: str) -> tuple[ReceiverStatus | None, str]:
        """Read the receiver at ``host``; return its status or an error key."""
        client = PTLevelClient(async_get_clientsession(self.hass), host)
        try:
            return await client.async_get_status(), ""
        except PTLevelConnectionError as err:
            _LOGGER.debug("PTLevel receiver at %s unreachable: %s", host, err)
            return None, "cannot_connect"
        except PTLevelUnsupportedError as err:
            _LOGGER.debug("PTLevel receiver at %s unsupported: %s", host, err)
            return None, "unsupported_receiver"


class PTLevelOptionsFlow(OptionsFlowWithReload):
    """Set up the tank's water depth and fill level.

    Both routes write the same two options. *Calibrate* derives the depth
    offset from a water depth measured by hand against the current reading,
    which is how an owner normally finds it; *tank settings* edits the offset
    and the full depth directly. Saving reloads the entry, so the depth and
    percentage entities appear or go away with their settings.
    """

    _baseline: tuple[datetime, TransmitterReading] | None = None
    """The report the receiver held when the calibrate form first opened.

    Calibration uses the first report that differs from it: the one the
    owner's button press sends after opening the form. A report is identified
    by its reading as well as its time, because two can share a time (as under
    a frozen test clock).
    """

    _pending: _Calibration | None = None
    """A calibration computed from a new report, waiting for confirmation."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Offer calibration or the tank settings."""
        return self.async_show_menu(step_id="init", menu_options=["calibrate", "tank"])

    async def async_step_tank(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the depth offset, the full depth and the capacity.

        The form shows each setting in the owner's unit (see ``units.py``) and
        stores it in inches or US gallons. An empty field removes its option.
        Without a depth offset there are no tank entities at all; a full depth
        adds the percentage, a capacity adds the tank capacity, and both add
        the water volume. Settings saved without an offset wait for one.
        """
        units = _tank_units(self.hass.config.units)
        if user_input is not None:
            options = {
                key: unit.to_stored(value)
                for key, unit in units.items()
                if (value := user_input.get(key)) is not None
            }
            return self.async_create_entry(data=options)

        saved = self.config_entry.options
        suggested = {
            key: unit.from_stored(saved[key])
            for key, unit in units.items()
            if key in saved
        }
        return self.async_show_form(
            step_id="tank",
            data_schema=self.add_suggested_values_to_schema(
                _tank_schema(units), suggested
            ),
            description_placeholders={
                "unit": units[CONF_DEPTH_OFFSET].unit,
                "volume_unit": units[CONF_CAPACITY].unit,
            },
        )

    async def async_step_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the depth offset from a depth measured against a fresh report.

        The owner opens the form, presses the transmitter's button and
        measures. The report the receiver held when the form opened is the
        baseline, and a submission is accepted only once a different report
        has arrived (``no_new_report`` until then), so the offset is always
        the measured depth minus the water column of a report sent after the
        form opened, never an older one with an ambiguous time. The receiver
        is read afresh on every show and submit, rather than relying on a poll
        up to a minute old. The new report and the resulting offset are then
        shown for confirmation, where the owner can save or go back to correct
        the depth without pressing the button again.

        Depths are shown and typed in the owner's unit (see ``units.py``) and
        stored in inches. A submission is also refused when the new report's
        water column, as the owner sees it, is under ``MIN_CALIBRATION_WATER_COLUMN``
        (``low_reading``, which looks like a chamber out of the water or a
        leaking tube), or when the offset falls outside ``DEPTH_OFFSET_RANGE``
        (``implausible_depth``). If the receiver does not answer once the
        procedure has started, the form comes back with ``cannot_read`` and
        keeps the baseline, so the owner's button press still counts. The form
        always keeps the depth the owner typed.

        The step aborts when the entry is not loaded or the receiver does not
        answer when the form first opens (``not_loaded``), before any report
        (``no_reading``), and for transmitter hardware without a verified scale
        (``unverified_scale``). The full depth, if set, is kept.
        """
        units = length_unit(self.hass.config.units)
        read = await self._read_receiver()
        if read is None or (not read.answered and self._baseline is None):
            return self.async_abort(reason="not_loaded")
        data = read.data
        if data.reading is None or data.last_report is None:
            return self.async_abort(reason="no_reading")
        if (water_column := data.reading.water_column_inches) is None:
            return self.async_abort(reason="unverified_scale")
        if not read.answered:
            return self._show_calibrate(
                units,
                water_column,
                data.last_report,
                user_input,
                {"base": "cannot_read"},
            )
        report = (data.last_report, data.reading)
        if self._baseline is None:
            self._baseline = report

        errors: dict[str, str] = {}
        if user_input is not None:
            measured_depth = units.to_stored(user_input[CONF_MEASURED_DEPTH])
            offset = units.round_stored(measured_depth - water_column)
            low, high = DEPTH_OFFSET_RANGE
            if report == self._baseline:
                errors["base"] = "no_new_report"
            elif _shown(units, water_column) < units.from_stored(
                MIN_CALIBRATION_WATER_COLUMN
            ):
                errors["base"] = "low_reading"
            elif not low <= offset <= high:
                errors[CONF_MEASURED_DEPTH] = "implausible_depth"
            else:
                self._pending = _Calibration(
                    water_column=water_column,
                    reported=data.last_report,
                    measured_depth=measured_depth,
                    offset=offset,
                )
                return await self.async_step_calibrate_confirm()

        return self._show_calibrate(
            units, water_column, data.last_report, user_input, errors
        )

    def _show_calibrate(
        self,
        units: FormUnit,
        water_column: float,
        reported: datetime,
        user_input: dict[str, Any] | None,
        errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Show the calibrate form, keeping whatever depth the owner last gave.

        On a re-show after an error that is the owner's submission, already
        in their unit; coming back from the confirmation it is the depth they
        confirmed, which is stored in inches.
        """
        suggested = user_input
        if suggested is None and self._pending is not None:
            suggested = {
                CONF_MEASURED_DEPTH: units.from_stored(self._pending.measured_depth)
            }
        return self.async_show_form(
            step_id="calibrate",
            data_schema=self.add_suggested_values_to_schema(
                _calibrate_schema(units), suggested
            ),
            errors=errors,
            description_placeholders={
                "water_column": _format_shown(units, water_column),
                "reported": _when(reported),
                "unit": units.unit,
            },
        )

    async def async_step_calibrate_confirm(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Show the report and offset a calibration will use, to save or change."""
        if (pending := self._pending) is None:
            return await self.async_step_calibrate()
        units = length_unit(self.hass.config.units)
        return self.async_show_menu(
            step_id="calibrate_confirm",
            menu_options=["calibrate_save", "calibrate"],
            description_placeholders={
                "water_column": _format_shown(units, pending.water_column),
                "reported": _when(pending.reported),
                "measured_depth": units.format(pending.measured_depth),
                "offset": units.format(pending.offset),
                "unit": units.unit,
            },
        )

    async def async_step_calibrate_save(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Save the confirmed depth offset, keeping the full depth."""
        if (pending := self._pending) is None:
            return await self.async_step_calibrate()
        return self.async_create_entry(
            data={**self.config_entry.options, CONF_DEPTH_OFFSET: pending.offset}
        )

    async def _read_receiver(self) -> _Read | None:
        """Read the receiver now and return the entry's snapshot.

        ``None`` when the entry is not loaded, before or after the read: it
        can unload or reload meanwhile, and a refresh skipped after shutdown
        leaves ``last_update_success`` as it was. Otherwise the snapshot comes
        with whether the receiver answered just now; when it did not, the
        snapshot is the coordinator's last good one, which calibration must
        not mistake for a current reading.
        """
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return None
        coordinator: PTLevelCoordinator = entry.runtime_data
        await coordinator.async_refresh()
        if entry.state is not ConfigEntryState.LOADED:
            return None
        if entry.runtime_data is not coordinator:
            return None
        return _Read(data=coordinator.data, answered=coordinator.last_update_success)


@dataclass(frozen=True, slots=True)
class _Calibration:
    """A calibration computed from a new report, waiting for confirmation.

    Depths are in inches, whatever unit the owner typed them in.
    """

    water_column: float
    reported: datetime
    measured_depth: float
    offset: float


@dataclass(frozen=True, slots=True)
class _Read:
    """The result of reading the receiver for calibration."""

    data: PTLevelData
    answered: bool


def _shown(units: FormUnit, water_column: float) -> float:
    """Return the water column as the owner sees it: in their unit, never negative."""
    return units.from_stored(water_column) if water_column > 0 else 0.0


def _format_shown(units: FormUnit, water_column: float) -> str:
    """Return the water column as text, as the owner sees it."""
    return f"{_shown(units, water_column):.{units.decimals}f}"


def _when(moment: datetime) -> str:
    """Return a report time in local time, to the second."""
    return dt_util.as_local(moment).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_host(text: str) -> str | None:
    """Return a bare hostname or IP address, or ``None`` if ``text`` is not one.

    Brackets around an IPv6 address are dropped. URLs, ports, paths and anything
    else ``yarl`` cannot use as a host are rejected rather than guessed at.
    """
    host = text.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(char in host for char in "/@?#[] "):
        return None
    if host.count(":") == 1:  # a port, not an IPv6 address
        return None
    try:
        URL.build(scheme="http", host=host)
    except ValueError:
        return None
    return host


def _schema(defaults: dict[str, Any] | None) -> probatio.Schema:
    """Return the address form, prefilled from ``defaults``."""
    host = (defaults or {}).get(CONF_HOST)
    marker = (
        probatio.Required(CONF_HOST)
        if host is None
        else probatio.Required(CONF_HOST, default=host)
    )
    return probatio.Schema({marker: str})
