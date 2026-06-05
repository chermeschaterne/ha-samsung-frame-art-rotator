"""
The Samsung Frame Art Rotator integration.

Sets up the DataUpdateCoordinator and forwards it to the platform
modules (sensor, switch, button).
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_ROTATION_TIME, DOMAIN, PLATFORMS
from .coordinator import FrameArtCoordinator

_LOGGER = logging.getLogger(__name__)

# Service name constant — keep in sync with services.yaml
SERVICE_SET_ROTATION_TIME = "set_rotation_time"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung Frame Art Rotator from a config entry."""
    coordinator = FrameArtCoordinator(hass, entry)

    # Async one-time init: load state.json + saved TV token from disk.
    # Must happen BEFORE the first refresh, but AFTER constructor.
    try:
        await coordinator.async_load_initial_state()
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Initial state load failed (will retry in background): %s", e)
        # Don't fail entry setup - entities will be "unavailable" until next update

    # First refresh: validate the Immich share URL is reachable.
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Initial refresh failed (will retry in background): %s", e)
        # Don't fail entry setup - entities will be "unavailable" until next update

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start_listeners()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    entry.async_on_unload(coordinator.async_stop_listeners)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: FrameArtCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # The coordinator's stop_listeners is called via async_on_unload.
        # The aiohttp session is owned by HA - do not close it.
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _normalize_time(value: object) -> str:
    """Normalize the value passed to the set_rotation_time service to
    a 'HH:MM' string. Accepts datetime.time objects (time selector
    default in modern HA) and 'HH:MM' or 'HH:MM:SS' strings."""
    if value is None:
        raise ValueError("time value is required")
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    if isinstance(value, str):
        s = value.strip()
        if len(s) >= 5 and s[2] == ":":
            return s[:5]
    raise ValueError(
        f"Invalid time value: {value!r} (expected datetime.time or 'HH:MM[:SS]' string)"
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register integration-level services.

    Called once when HA loads the integration, even before any
    config entry is set up. Safe to register services here.
    """

    async def _handle_set_rotation_time(call: ServiceCall) -> None:
        try:
            new_time = _normalize_time(call.data.get("time"))
        except ValueError as e:
            _LOGGER.error("set_rotation_time: %s", e)
            return

        target_entries = list(hass.config_entries.async_entries(DOMAIN))
        if not target_entries:
            _LOGGER.warning(
                "set_rotation_time called but no %s entries are configured", DOMAIN
            )
            return

        for entry in target_entries:
            new_options = {**entry.options, CONF_ROTATION_TIME: new_time}
            hass.config_entries.async_update_entry(entry, options=new_options)
            _LOGGER.info(
                "set_rotation_time: updated entry %s to %s", entry.entry_id, new_time
            )
        # If the entry is currently loaded, the update_listener
        # (added in async_setup_entry) reloads it, which restarts the
        # coordinator's daily timer with the new time. Unloaded
        # entries pick up the new option on next load.

    hass.services.async_register(DOMAIN, SERVICE_SET_ROTATION_TIME, _handle_set_rotation_time)
    return True
