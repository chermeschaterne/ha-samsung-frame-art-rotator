"""
The Samsung Frame Art Rotator integration.

Sets up the DataUpdateCoordinator and forwards it to the platform
modules (sensor, switch, button).
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import FrameArtCoordinator

_LOGGER = logging.getLogger(__name__)


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
