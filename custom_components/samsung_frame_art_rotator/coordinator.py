"""
DataUpdateCoordinator for the Samsung Frame Art Rotator.

The coordinator:
  - Fetches the current album size from Immich every UPDATE_INTERVAL
  - Tracks the next scheduled rotation
  - Caches the latest state in `coordinator.data` for entities to read

It also owns the daily rotation schedule (via `async_track_time_interval`).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BRIGHTNESS_LEVEL,
    CONF_DISABLE_SENSOR,
    CONF_FRAME_HOST,
    CONF_FRAME_MAC,
    CONF_MATTE,
    CONF_MOTION_SENSOR,
    CONF_MOTION_TIMEOUT,
    CONF_ROTATION_TIME,
    DEFAULT_BRIGHTNESS_LEVEL,
    DEFAULT_DISABLE_SENSOR,
    DEFAULT_MATTE,
    DEFAULT_MOTION_TIMEOUT,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .frame_client import FrameClient
from .immich_client import ImmichClient
from .rotation import RotationEngine
from .state import State, StateStore

_LOGGER = logging.getLogger(__name__)


class FrameArtCoordinator(DataUpdateCoordinator[State]):
    """Coordinator for the Samsung Frame Art Rotator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.config = self._resolve_config(entry)

        # State store lives in the HA config dir under .storage/
        state_path = hass.config.path(
            f".storage/{DOMAIN}/{entry.entry_id}_state.json"
        )
        self.state_store = StateStore(state_path)
        self._state_path = state_path

        # aiohttp session shared by Immich + (optionally) HA motion polling
        self.session = async_get_clientsession(hass)

        # Build clients
        self.immich = ImmichClient(self.config["immich_share_url"], self.session)
        self.frame = FrameClient(
            host=self.config["frame_host"],
            mac=self.config["frame_mac"],
            client_name=self.config["client_name"],
            matte=self.config["matte"],
            token=self._load_token(),
        )
        self.engine = RotationEngine(self.config, self.state_store,
                                     self.frame, self.immich)

        self._unsub_daily = None
        self._unsub_motion = None
        self._motion_standby = False
        self._next_rotation: Optional[datetime] = None

    @staticmethod
    def _resolve_config(entry: ConfigEntry) -> dict:
        """Build the runtime config dict from the config-entry data."""
        data = entry.data
        options = entry.options
        return {
            "immich_share_url": data["immich_share_url"],
            "frame_host": data["frame_host"],
            "frame_mac": data["frame_mac"],
            "client_name": data.get("client_name", "FrameArtRotator"),
            "matte": data.get("matte", DEFAULT_MATTE),
            "enabled": options.get("enabled", True),
            "rotation_time": options.get("rotation_time", "06:00"),
            "brightness_level": options.get("brightness_level", DEFAULT_BRIGHTNESS_LEVEL),
            "disable_sensor": options.get("disable_sensor", DEFAULT_DISABLE_SENSOR),
            "motion_sensor": options.get("motion_sensor", ""),
            "motion_timeout_minutes": options.get("motion_timeout_minutes",
                                                   DEFAULT_MOTION_TIMEOUT),
        }

    def _token_path(self):
        return self.hass.config.path(
            f".storage/{DOMAIN}/{self.entry.entry_id}_tv_token"
        )

    def _load_token(self) -> Optional[str]:
        p = self._token_path()
        if p.exists():
            try:
                t = p.read_text().strip()
                return t or None
            except OSError as e:  # noqa: PERF203
                _LOGGER.debug("Could not read token: %s", e)
        return None

    def _save_token(self, token: str) -> None:
        if not token:
            return
        p = self._token_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(token)
        try:
            p.chmod(0o600)
        except OSError:
            pass
        self.frame.token = token

    async def _async_update_data(self) -> State:
        """Fetch the latest album size + cache state.

        Called every UPDATE_INTERVAL by the DataUpdateCoordinator.
        On error: raises UpdateFailed -> entity becomes "unavailable".
        """
        try:
            n = await self.engine.refresh_album()
            _LOGGER.debug("Periodic refresh: %d assets", n)
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Album refresh failed: {err}") from err

        # If the frame connection established a new token, persist it
        if self.frame.token and self.frame.token != self._load_token():
            self._save_token(self.frame.token)

        return self.state_store.state

    async def async_start_listeners(self) -> None:
        """Start the daily-rotation timer and optional motion listener."""
        # Daily rotation
        if self.config["enabled"]:
            hh, mm = self.config["rotation_time"].split(":")
            self._unsub_daily = self.hass.helpers.event.async_track_time_change(
                self.hass,
                self._handle_scheduled_rotation,
                hour=int(hh),
                minute=int(mm),
                second=0,
            )
            self._recompute_next_rotation()

        # Optional motion sensor
        motion_entity = self.config.get("motion_sensor", "")
        if motion_entity:
            self._unsub_motion = self.hass.helpers.event.async_track_state_change_event(
                self.hass,
                [motion_entity],
                self._handle_motion_change,
            )
            _LOGGER.info("Motion listener attached to %s", motion_entity)

    async def async_stop_listeners(self) -> None:
        if self._unsub_daily:
            self._unsub_daily()
            self._unsub_daily = None
        if self._unsub_motion:
            self._unsub_motion()
            self._unsub_motion = None

    def _recompute_next_rotation(self) -> None:
        try:
            hh, mm = self.config["rotation_time"].split(":")
            now = dt_util.now()
            target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            self._next_rotation = target
        except Exception:  # noqa: BLE001
            self._next_rotation = None

    @property
    def next_rotation(self) -> Optional[datetime]:
        return self._next_rotation

    async def _handle_scheduled_rotation(self, _now) -> None:
        _LOGGER.info("=== Scheduled daily rotation starting ===")
        try:
            result = await self.engine.run_rotation(force=False)
            _LOGGER.info("Scheduled rotation: %s", result.get("status"))
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("Scheduled rotation failed: %s", e)
        self._recompute_next_rotation()
        # Notify entities
        self.async_update_listeners()

    async def _handle_motion_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        state_val = new_state.state.lower()
        timeout_min = int(self.config.get("motion_timeout_minutes", DEFAULT_MOTION_TIMEOUT))
        if state_val == "on":
            if self._motion_standby:
                _LOGGER.info("Motion detected - waking TV")
                self._motion_standby = False
                await self.engine.wake()
        elif state_val == "off":
            # Only standby once we have not seen motion for a while
            # (HA's motion sensor already has its own hold-time; if user
            # configured a longer effective standby window, schedule a check)
            self.hass.async_create_task(
                self._maybe_standby_after_timeout(timeout_min)
            )

    async def _maybe_standby_after_timeout(self, timeout_min: int) -> None:
        """Re-check after `timeout_min` minutes; if still no motion, standby."""
        await asyncio.sleep(timeout_min * 60)
        motion_entity = self.config.get("motion_sensor", "")
        if not motion_entity:
            return
        st = self.hass.states.get(motion_entity)
        if st and st.state.lower() == "off" and not self._motion_standby:
            _LOGGER.info("No motion for %d min - putting TV in standby", timeout_min)
            self._motion_standby = True
            await self.engine.standby()

    @property
    def motion_standby(self) -> bool:
        return self._motion_standby


# asyncio is imported lazily inside methods to keep module init cheap
import asyncio  # noqa: E402
