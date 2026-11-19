"""Config flow for ParemTech PTLevel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, UnitOfLength
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

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult

    from .coordinator import PTLevelData

_LOGGER = logging.getLogger(__name__)

MAX_DEPTH = 600.0
"""Deepest water depth the forms accept, in inches (50 ft)."""


def _inches(minimum: float, maximum: float) -> NumberSelector:
    """Return a typed-in number field in inches, to a tenth of an inch."""
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=0.1,
            unit_of_measurement=UnitOfLength.INCHES,
            mode=NumberSelectorMode.BOX,
        )
    )


TANK_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_DEPTH_OFFSET): _inches(*DEPTH_OFFSET_RANGE),
        probatio.Optional(CONF_FULL_DEPTH): _inches(1.0, MAX_DEPTH),
    }
)
"""Both tank settings are optional, and an empty field removes its option.

The depth offset deliberately has no default: an owner who opens the form
only to set the full depth must not end up with an uncalibrated offset of
zero, which would create a Water depth that is really the water column.
"""
CALIBRATE_SCHEMA = probatio.Schema(
    {probatio.Required(CONF_MEASURED_DEPTH): _inches(0.0, MAX_DEPTH)}
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

    _shown_report: datetime | None = None
    """The report the calibrate form last showed, to catch one arriving meanwhile."""

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

        An empty field removes its option. Without a depth offset there are no
        tank entities at all, and without a full depth there is no percentage;
        a full depth saved on its own waits for the offset.
        """
        if user_input is not None:
            options = {
                key: round(value, 1)
                for key in (CONF_DEPTH_OFFSET, CONF_FULL_DEPTH)
                if (value := user_input.get(key)) is not None
            }
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="tank",
            data_schema=self.add_suggested_values_to_schema(
                TANK_SCHEMA, self.config_entry.options
            ),
        )

    async def async_step_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the depth offset from a measured water depth.

        The offset is the measured depth minus the water column of the report
        the form showed, so the owner measures right after a fresh report. If
        another report arrives while the form is open, the submission is
        refused with ``new_report`` and the form shows the new reading rather
        than silently using a value the owner never saw. A result outside
        ``DEPTH_OFFSET_RANGE`` is refused as a mistake. The full depth, if set,
        is kept.

        The step aborts, each with its own explanation, when the entry is not
        loaded (``not_loaded``), before any report (``no_reading``), for
        transmitter hardware without a verified scale (``unverified_scale``),
        and when the water column, at the one decimal the owner sees, is under
        ``MIN_CALIBRATION_WATER_COLUMN`` (``low_reading``), which looks the
        same as a chamber out of the water or a leaking air tube. Comparing
        the shown value means a refused reading never displays as 1.0 in.
        """
        data = self._loaded_data()
        if data is None:
            return self.async_abort(reason="not_loaded")
        if data.reading is None or data.last_report is None:
            return self.async_abort(reason="no_reading")
        if (water_column := data.reading.water_column_inches) is None:
            return self.async_abort(reason="unverified_scale")
        # A negative column shows as 0.0, never -0.0 or a negative depth.
        shown_column = round(water_column, 1) if water_column > 0 else 0.0
        if shown_column < MIN_CALIBRATION_WATER_COLUMN:
            return self.async_abort(
                reason="low_reading",
                description_placeholders={"water_column": f"{shown_column:.1f}"},
            )
        reported = data.last_report

        errors: dict[str, str] = {}
        if user_input is not None:
            offset = round(user_input[CONF_MEASURED_DEPTH] - water_column, 1)
            low, high = DEPTH_OFFSET_RANGE
            if reported != self._shown_report:
                errors["base"] = "new_report"
            elif low <= offset <= high:
                return self.async_create_entry(
                    data={**self.config_entry.options, CONF_DEPTH_OFFSET: offset}
                )
            else:
                errors[CONF_MEASURED_DEPTH] = "implausible_depth"

        self._shown_report = reported
        return self.async_show_form(
            step_id="calibrate",
            data_schema=CALIBRATE_SCHEMA,
            errors=errors,
            description_placeholders={
                "water_column": f"{water_column:.1f}",
                "reported": dt_util.as_local(reported).strftime("%Y-%m-%d %H:%M"),
            },
        )

    def _loaded_data(self) -> PTLevelData | None:
        """Return the entry's latest coordinator snapshot, or ``None`` if not loaded."""
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data.data


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
