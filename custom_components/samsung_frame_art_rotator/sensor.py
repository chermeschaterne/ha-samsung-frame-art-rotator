"""Sensor platform for Samsung Frame Art Rotator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FrameArtCoordinator

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="album_size",
        name="Album size",
        icon="mdi:image-multiple",
    ),
    SensorEntityDescription(
        key="current_image",
        name="Current image",
        icon="mdi-image-frame",
    ),
    SensorEntityDescription(
        key="next_rotation",
        name="Next rotation",
        device_class="timestamp",
        icon="mdi-calendar-clock",
    ),
    SensorEntityDescription(
        key="last_rotation",
        name="Last rotation",
        device_class="timestamp",
        icon="mdi-history",
    ),
    SensorEntityDescription(
        key="last_rotation_status",
        name="Last rotation status",
        icon="mdi-check-circle",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    coordinator: FrameArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FrameArtSensor(coordinator, description) for description in SENSORS
    )


class FrameArtSensor(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """A single sensor backed by the coordinator state."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FrameArtCoordinator,
                 description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Samsung Frame",
            manufacturer="Samsung",
            model="The Frame",
        )

    @property
    def native_value(self) -> Any:
        s = self.coordinator.data
        key = self.entity_description.key
        if key == "album_size":
            return len(s.asset_order)
        if key == "current_image":
            return s.current_immich_id
        if key == "next_rotation":
            return self.coordinator.next_rotation
        if key == "last_rotation":
            if not s.last_rotation:
                return None
            try:
                # Tolerate both formats: new "+00:00" suffix and old
                # "Z" suffix (from state files written by <1.0.3).
                # `fromisoformat` in Python 3.11+ accepts both directly.
                raw = s.last_rotation
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    # Belt-and-suspenders: if anything produced a naive
                    # datetime, treat it as UTC (the field is always UTC).
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                return None
        if key == "last_rotation_status":
            return s.last_rotation_status or "unknown"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self.coordinator.data
        if self.entity_description.key == "last_rotation_status":
            return {
                "last_error": s.last_rotation_error,
                "album_size": len(s.asset_order),
                "current_index": s.current_index,
            }
        if self.entity_description.key == "current_image":
            return {
                "content_id_on_frame": s.uploaded.get(s.current_immich_id)
                if s.current_immich_id else None,
                "current_index": s.current_index,
            }
        return None
