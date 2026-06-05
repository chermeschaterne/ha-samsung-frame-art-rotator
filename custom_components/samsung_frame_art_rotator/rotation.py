"""
Rotation engine: combines Immich, Frame, and State to perform one full
rotation cycle (pick next image, ensure uploaded, select on TV, set
brightness).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .frame_client import FrameClient
from .immich_client import ImmichClient
from .state import StateStore

_LOGGER = logging.getLogger(__name__)


class RotationEngine:
    def __init__(self, config: dict, state: StateStore,
                 frame: FrameClient, immich: ImmichClient):
        self._config = config
        self._state = state
        self._frame = frame
        self._immich = immich

    @property
    def enabled(self) -> bool:
        return self._config.get("enabled", True)

    @property
    def brightness_level(self) -> int:
        return int(self._config.get("brightness_level", 2))

    @property
    def disable_sensor(self) -> bool:
        return bool(self._config.get("disable_sensor", True))

    async def refresh_album(self) -> int:
        """Fetch the current album contents from Immich. Returns # of assets."""
        assets = await self._immich.list_assets()
        asset_ids = [a.id for a in assets]
        await self._state.update_assets(asset_ids)
        return len(asset_ids)

    async def run_rotation(self, force: bool = False) -> dict:
        """Perform a single rotation. Returns a status dict."""
        if not self.enabled and not force:
            return {"status": "skipped", "reason": "disabled",
                    "ts": datetime.now(timezone.utc).isoformat()}

        ts = datetime.now(timezone.utc).isoformat()
        result: dict = {"status": "running", "ts": ts}

        try:
            n = await self.refresh_album()
            result["album_size"] = n
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Album refresh failed: %s", e)
            result["status"] = "error"
            result["error"] = f"album_refresh: {e}"
            await self._state.set_last_rotation("error", str(e))
            return result

        if n == 0:
            result["status"] = "skipped"
            result["reason"] = "empty album"
            await self._state.set_last_rotation("skipped", "empty album")
            return result

        if not force:
            await self._state.advance()

        asset_id = self._state.current_asset_id()
        if not asset_id:
            result["status"] = "error"
            result["error"] = "no current asset"
            await self._state.set_last_rotation("error", "no current asset")
            return result

        result["immich_id"] = asset_id

        try:
            connected = await self._frame.connect(wake_if_needed=True)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Frame connect failed: %s", e)
            result["status"] = "error"
            result["error"] = f"frame_connect: {e}"
            await self._state.set_last_rotation("error", str(e))
            return result

        if not connected:
            result["status"] = "error"
            result["error"] = "frame unreachable (WoL did not help)"
            await self._state.set_last_rotation("error", result["error"])
            return result

        try:
            content_id = self._state.get_uploaded(asset_id)
            if content_id:
                _LOGGER.info("Image %s already on Frame (%s) - selecting",
                             asset_id, content_id)
                result["content_id"] = content_id
                result["action"] = "select"
            else:
                try:
                    img_bytes = await self._immich.download_original(asset_id)
                except Exception as e:  # noqa: BLE001
                    _LOGGER.error("Immich download failed: %s", e)
                    result["status"] = "error"
                    result["error"] = f"download: {e}"
                    await self._state.set_last_rotation("error", str(e))
                    return result

                content_id = await self._frame.upload(img_bytes)
                if not content_id:
                    result["status"] = "error"
                    result["error"] = "upload returned no content_id"
                    await self._state.set_last_rotation("error", result["error"])
                    return result

                await self._state.mark_uploaded(asset_id, content_id)
                result["content_id"] = content_id
                result["action"] = "upload_and_select"

            ok = await self._frame.select_image(content_id, show=False)
            if not ok:
                result["status"] = "error"
                result["error"] = "select_image failed"
                await self._state.set_last_rotation("error", result["error"])
                return result

            await self._frame.set_brightness(self.brightness_level)

            await self._state.set_last_rotation("ok")
            result["status"] = "ok"
            return result

        finally:
            await self._frame.close()

    async def run_rotation_now(self) -> dict:
        """Force a rotation immediately (used by manual button)."""
        return await self.run_rotation(force=True)

    async def wake(self) -> bool:
        """Send WoL + connect, ensure art mode is on."""
        try:
            if not await self._frame.connect(wake_if_needed=True):
                return False
            try:
                return await self._frame.set_art_mode(True)
            finally:
                await self._frame.close()
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("wake() failed: %s", e)
            return False

    async def standby(self) -> bool:
        """Put the Frame in standby (panel off, API still responsive)."""
        try:
            if not await self._frame.connect(wake_if_needed=False):
                return False
            try:
                return await self._frame.set_art_mode(False)
            finally:
                await self._frame.close()
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("standby() failed: %s", e)
            return False
