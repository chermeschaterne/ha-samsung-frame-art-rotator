"""Button platform for Samsung Frame Art Rotator."""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
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
    """Set up the button platform from a config entry."""
    coordinator: FrameArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        FrameArtRotateNowButton(coordinator, entry),
        FrameArtWakeButton(coordinator, entry),
        FrameArtStandbyButton(coordinator, entry),
    ])


class _BaseButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FrameArtCoordinator,
                 entry: ConfigEntry, name: str, icon: str) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{name.lower().replace(' ', '_')}"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Samsung Frame",
            manufacturer="Samsung",
            model="The Frame",
        )


class FrameArtRotateNowButton(_BaseButton):
    """Manually trigger a rotation right now."""

    def __init__(self, coordinator: FrameArtCoordinator,
                 entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Rotate now", "mdi-image-sync")

    async def async_press(self) -> None:
        await self._coordinator.engine.run_rotation_now()
        self.hass.async_create_task(self._coordinator.async_request_refresh())


class FrameArtWakeButton(_BaseButton):
    """Wake the Frame (WoL + enable art mode)."""

    def __init__(self, coordinator: FrameArtCoordinator,
                 entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Wake frame", "mdi-tv")

    async def async_press(self) -> None:
        await self._coordinator.engine.wake()


class FrameArtStandbyButton(_BaseButton):
    """Put the Frame in standby (panel off, API still responsive)."""

    def __init__(self, coordinator: FrameArtCoordinator,
                 entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Standby", "mdi-tv-off")

    async def async_press(self) -> None:
        await self._coordinator.engine.standby()
