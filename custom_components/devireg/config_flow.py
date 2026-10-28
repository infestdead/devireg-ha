"""Config flow for DEVIreg Smart."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import CannotConnect, DeviRegError, InvalidOtp, pair
from .const import (
    CONF_HOUSE_NAME,
    CONF_NAME,
    CONF_OTP,
    CONF_PEER_ID,
    CONF_PRIVATE_KEY,
    CONF_ROOMS,
    CONF_USER_NAME,
    DOMAIN,
)
from .sdg import public_key

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OTP): str,
        vol.Optional(CONF_USER_NAME, default="Home Assistant"): str,
    }
)


class DeviRegConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair Home Assistant with a house shared from the DEVIsmart app."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await pair(user_input[CONF_OTP], user_input[CONF_USER_NAME])
            except InvalidOtp:
                errors["base"] = "invalid_otp"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except DeviRegError:
                errors["base"] = "no_thermostats"
            except Exception:
                _LOGGER.exception("Unexpected error while pairing")
                errors["base"] = "unknown"
            else:
                configured = {
                    room[CONF_PEER_ID]
                    for entry in self._async_current_entries()
                    for room in entry.data.get(CONF_ROOMS, [])
                }
                if any(room.peer_id in configured for room in result.rooms):
                    return self.async_abort(reason="already_configured")

                # Each pairing creates a new key, so the key identifies this entry
                our_id = public_key(bytes.fromhex(result.private_key)).hex()
                await self.async_set_unique_id(our_id)
                return self.async_create_entry(
                    title=result.house_name,
                    data={
                        CONF_PRIVATE_KEY: result.private_key,
                        CONF_HOUSE_NAME: result.house_name,
                        CONF_ROOMS: [
                            {CONF_PEER_ID: room.peer_id, CONF_NAME: room.name}
                            for room in result.rooms
                        ],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
