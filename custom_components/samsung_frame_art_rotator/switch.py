"""Switch platform for Samsung Frame Art Rotator."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FrameArtCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform from a config entry."""
    coordinator: FrameArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FrameArtEnabledSwitch(coordinator, entry)])


class FrameArtEnabledSwitch(SwitchEntity):
    """Master switch: when OFF, scheduled rotation is paused."""

    _attr_has_entity_name = True
    _attr_icon = "mdi-toggle-switch"

    def __init__(self, coordinator: FrameArtCoordinator,
                 entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_enabled"
        self._attr_name = "Rotation enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Samsung Frame",
            manufacturer="Samsung",
            model="The Frame",
        )

    @property
    def is_on(self) -> bool:
        return self._coordinator.config.get("enabled", True)

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    async def async_turn_on(self, **kwargs: Any) -> None:
        new_opts = {**self._entry.options, "enabled": True}
        self.hass.config_entries.async_update_entry(self._entry, options=new_opts)
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        new_opts = {**self._entry.options, "enabled": False}
        self.hass.config_entries.async_update_entry(self._entry, options=new_opts)
        await self._coordinator.async_request_refresh()
