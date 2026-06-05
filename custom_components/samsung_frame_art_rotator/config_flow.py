"""Config flow for Samsung Frame Art Rotator."""
from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import selector

from .const import (
    CONF_BRIGHTNESS_LEVEL,
    CONF_CLIENT_NAME,
    CONF_DISABLE_SENSOR,
    CONF_FRAME_HOST,
    CONF_FRAME_MAC,
    CONF_IMMICH_SHARE_URL,
    CONF_MATTE,
    CONF_MOTION_SENSOR,
    CONF_MOTION_TIMEOUT,
    CONF_ROTATION_TIME,
    DEFAULT_BRIGHTNESS_LEVEL,
    DEFAULT_CLIENT_NAME,
    DEFAULT_DISABLE_SENSOR,
    DEFAULT_MATTE,
    DEFAULT_MOTION_TIMEOUT,
    DEFAULT_ROTATION_TIME,
    DOMAIN,
)
from .immich_client import ImmichClient, ImmichError

_LOGGER = logging.getLogger(__name__)


def _user_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_IMMICH_SHARE_URL): cv.string,
        vol.Required(CONF_FRAME_HOST): cv.string,
        vol.Required(CONF_FRAME_MAC): cv.string,
        vol.Optional(CONF_CLIENT_NAME, default=DEFAULT_CLIENT_NAME): cv.string,
        vol.Optional(CONF_MATTE, default=DEFAULT_MATTE): vol.In([
            "none", "modernthin", "modern", "modernwide", "flexible",
            "shadowbox", "panoramic", "triptych", "mix", "squares",
            "flexible_apricot", "flexible_black", "flexible_white",
            "shadowbox_warm", "shadowbox_cool", "modern_apricot",
            "modernwide_burgandy", "triptych_black", "squares_sage",
            "squares_seafoam",
        ]),
        # NOTE: rotation_time is intentionally NOT in the user (initial)
        # schema. The user sets it later via Configure, the
        # samsung_frame_art_rotator.set_rotation_time service, or
        # by editing entry.options. Default is 06:00.
    })


def _options_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    # The stored rotation_time is a "HH:MM" string. The time selector
    # wants a `time` object as default. Convert.
    rot_default = d.get("rotation_time", DEFAULT_ROTATION_TIME)
    if isinstance(rot_default, str):
        hh, mm = rot_default.split(":")[:2]
        rot_default = dt_time(int(hh), int(mm), 0)
    return vol.Schema({
        vol.Optional("enabled", default=d.get("enabled", True)): cv.boolean,
        vol.Optional(CONF_ROTATION_TIME, default=rot_default
                     ): selector({"time": {}}),
        vol.Optional(CONF_BRIGHTNESS_LEVEL,
                     default=d.get("brightness_level", DEFAULT_BRIGHTNESS_LEVEL)
                     ): vol.All(int, vol.Range(min=1, max=10)),
        vol.Optional(CONF_DISABLE_SENSOR,
                     default=d.get("disable_sensor", DEFAULT_DISABLE_SENSOR)
                     ): cv.boolean,
        vol.Optional(CONF_MOTION_SENSOR,
                     default=d.get("motion_sensor", "")): cv.string,
        vol.Optional(CONF_MOTION_TIMEOUT,
                     default=d.get("motion_timeout_minutes", DEFAULT_MOTION_TIMEOUT)
                     ): vol.All(int, vol.Range(min=1, max=120)),
    })


async def _validate_immich(hass: HomeAssistant, share_url: str) -> None:
    session = async_get_clientsession(hass)
    client = ImmichClient(share_url, session)
    try:
        await client.get_album_id()
    except ImmichError as e:
        raise InvalidImmichShare(str(e)) from e
    # Session is owned by HA - do not close it


class SamsungFrameArtRotatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Samsung Frame Art Rotator."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_immich(self.hass, user_input[CONF_IMMICH_SHARE_URL])
            except InvalidImmichShare:
                errors["base"] = "invalid_immich_share"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                # Don't allow two entries with the same share URL + host
                await self.async_set_unique_id(
                    f"{user_input[CONF_IMMICH_SHARE_URL]}|{user_input[CONF_FRAME_HOST]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Samsung Frame Art Rotator",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow — runtime settings (enabled, rotation time, brightness, motion)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # time selector returns "HH:MM:SS" - normalize to "HH:MM"
            t = user_input.get(CONF_ROTATION_TIME)
            if t is not None and hasattr(t, "strftime"):
                t = t.strftime("%H:%M")
            elif isinstance(t, str) and len(t) >= 5:
                t = t[:5]
            user_input[CONF_ROTATION_TIME] = t or "06:00"
            return self.async_create_entry(title="", data=user_input)

        # Merge config-flow values (entry.data) under runtime overrides
        # (entry.options), so the options form pre-fills with the
        # rotation_time / brightness_level / etc. that the user originally
        # set during the initial config flow.
        current = {**self.config_entry.data, **self.config_entry.options}
        # Convert stored "HH:MM" to time object for the time selector
        rot = current.get(CONF_ROTATION_TIME, DEFAULT_ROTATION_TIME)
        hh, mm = rot.split(":")[:2]
        current[CONF_ROTATION_TIME] = f"{hh}:{mm}"

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
        )


class InvalidImmichShare(Exception):
    """Raised when the Immich share URL is invalid or unreachable."""
