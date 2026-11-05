"""Config flow for ParemTech PTLevel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .ptlevel import (
    PTLevelClient,
    PTLevelConnectionError,
    PTLevelUnsupportedError,
    ReceiverStatus,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)


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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the receiver's address and validate it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
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
            host = user_input[CONF_HOST].strip()
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


def _schema(defaults: dict[str, Any] | None) -> probatio.Schema:
    """Return the address form, prefilled from ``defaults``."""
    host = (defaults or {}).get(CONF_HOST)
    marker = (
        probatio.Required(CONF_HOST)
        if host is None
        else probatio.Required(CONF_HOST, default=host)
    )
    return probatio.Schema({marker: str})
