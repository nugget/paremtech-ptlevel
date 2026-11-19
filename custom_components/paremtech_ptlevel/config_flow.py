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
from .units import displayed, format_length, inches_to_field, length_unit, to_inches

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.util.unit_system import UnitSystem

    from .coordinator import PTLevelCoordinator, PTLevelData
    from .ptlevel import TransmitterReading

_LOGGER = logging.getLogger(__name__)

MAX_DEPTH = 600.0
"""Deepest water depth the forms accept, in inches (50 ft)."""

TANK_LENGTH_RANGES: dict[str, tuple[float, float]] = {
    CONF_DEPTH_OFFSET: DEPTH_OFFSET_RANGE,
    CONF_FULL_DEPTH: (1.0, MAX_DEPTH),
}
"""Each tank setting's accepted range, in the stored unit (inches)."""


def _length_field(unit: str, low: float, high: float) -> NumberSelector:
    """Return a typed-in length field in ``unit``, for a range in inches.

    ``step`` only sets the keyboard increment, and ``any`` keeps fractional
    converted bounds from making ordinary entries look off-step.
    """
    return NumberSelector(
        NumberSelectorConfig(
            min=inches_to_field(low, unit),
            max=inches_to_field(high, unit),
            step="any",
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


def _tank_schema(unit: str) -> probatio.Schema:
    """Return the tank settings form, with lengths in ``unit``.

    Both settings are optional, and an empty field removes its option. The
    depth offset deliberately has no default: an owner who opens the form
    only to set the full depth must not end up with an uncalibrated offset of
    zero, which would create a Water depth that is really the water column.
    """
    return probatio.Schema(
        {
            probatio.Optional(key): _length_field(unit, *TANK_LENGTH_RANGES[key])
            for key in TANK_LENGTH_RANGES
        }
    )


def _calibrate_schema(unit: str) -> probatio.Schema:
    """Return the calibrate form, taking the measured depth in the owner's unit."""
    return probatio.Schema(
        {probatio.Required(CONF_MEASURED_DEPTH): _length_field(unit, 0.0, MAX_DEPTH)}
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

    _prefilled: dict[str, float] | None = None
    """The tank form's prefilled values, in the owner's unit, by setting.

    A submitted value equal to its prefill was left untouched, so the stored
    value is kept as it is instead of being converted back from the rounded
    prefill, which would quietly change a calibrated offset (4.7719 in is
    prefilled as 4.77).
    """

    _shown_system: UnitSystem | None = None
    """The unit system the last form was shown in.

    Submissions are read in its units, so a change to Home Assistant's unit
    system while a form is open cannot reinterpret what the owner typed (a
    132 mm offset saved as 132 in).
    """

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Offer calibration or the tank settings."""
        return self.async_show_menu(step_id="init", menu_options=["calibrate", "tank"])

    async def async_step_tank(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the depth offset and the full depth.

        The form shows lengths in the owner's unit (see ``units.py``) and
        stores them in inches. An empty field removes its option. Without a
        depth offset there are no tank entities at all, and without a full
        depth there is no percentage; a full depth saved on its own waits for
        the offset. A setting submitted unchanged from its prefill keeps its
        stored value exactly.
        """
        unit = length_unit(self._unit_system(user_input))
        saved = self.config_entry.options
        if user_input is not None:
            options = {
                key: self._kept_or(key, value, lambda v: to_inches(v, unit))
                for key in TANK_LENGTH_RANGES
                if (value := user_input.get(key)) is not None
            }
            return self.async_create_entry(data=options)

        suggested = {
            key: inches_to_field(saved[key], unit)
            for key in TANK_LENGTH_RANGES
            if key in saved
        }
        self._prefilled = suggested
        return self.async_show_form(
            step_id="tank",
            data_schema=self.add_suggested_values_to_schema(
                _tank_schema(unit), suggested
            ),
            description_placeholders={"unit": unit},
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
        unit = length_unit(self._unit_system(user_input))
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
                unit,
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
            measured_depth = to_inches(user_input[CONF_MEASURED_DEPTH], unit)
            offset = round(measured_depth - water_column, 4)
            low, high = DEPTH_OFFSET_RANGE
            if report == self._baseline:
                errors["base"] = "no_new_report"
            elif displayed(max(water_column, 0.0), unit) < displayed(
                MIN_CALIBRATION_WATER_COLUMN, unit
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
            unit, water_column, data.last_report, user_input, errors
        )

    def _show_calibrate(
        self,
        unit: str,
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
                CONF_MEASURED_DEPTH: inches_to_field(self._pending.measured_depth, unit)
            }
        return self.async_show_form(
            step_id="calibrate",
            data_schema=self.add_suggested_values_to_schema(
                _calibrate_schema(unit), suggested
            ),
            errors=errors,
            description_placeholders={
                "water_column": format_length(max(water_column, 0.0), unit),
                "reported": _when(reported),
                "unit": unit,
            },
        )

    async def async_step_calibrate_confirm(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Show the report and offset a calibration will use, to save or change."""
        if (pending := self._pending) is None:
            return await self.async_step_calibrate()
        # The confirmation belongs to the form just submitted, so it keeps
        # that form's units.
        unit = length_unit(self._shown_system or self.hass.config.units)
        return self.async_show_menu(
            step_id="calibrate_confirm",
            menu_options=["calibrate_save", "calibrate"],
            description_placeholders={
                "water_column": format_length(max(pending.water_column, 0.0), unit),
                "reported": _when(pending.reported),
                "measured_depth": format_length(pending.measured_depth, unit),
                "offset": format_length(pending.offset, unit),
                "unit": unit,
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

    def _kept_or(
        self, key: str, value: float, convert: Callable[[float], float]
    ) -> float:
        """Return the stored ``key`` if ``value`` is its untouched prefill.

        Otherwise convert ``value`` from the owner's unit for storage.
        """
        saved = self.config_entry.options
        if key in saved and self._prefilled and self._prefilled.get(key) == value:
            return saved[key]
        return convert(value)

    def _unit_system(self, user_input: dict[str, Any] | None) -> UnitSystem:
        """Return the unit system to show a form in, or to read a submission in.

        Showing a form (``user_input`` is ``None``) takes Home Assistant's
        current unit system and remembers it; reading a submission uses the
        one the form was shown in.
        """
        if user_input is None or self._shown_system is None:
            self._shown_system = self.hass.config.units
        return self._shown_system

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
