"""
Rotation engine: combines Immich, Frame, and State to perform one
full rotation cycle (pick next image, ensure uploaded, select on TV,
set brightness).

This is the single source of truth for "what happens during a rotation".
The scheduler and the web UI both call `run_rotation()`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .config import AddonConfig
from .frame_client import FrameClient
from .immich_client import ImmichClient
from .state import StateStore

logger = logging.getLogger(__name__)


class RotationEngine:
    def __init__(self, config: AddonConfig, state: StateStore,
                 frame: FrameClient, immich: ImmichClient):
        self._config = config
        self._state = state
        self._frame = frame
        self._immich = immich

    async def refresh_album(self) -> int:
        """
        Fetch the current album contents from Immich and update state.
        Returns the number of assets.
        """
        assets = await self._immich.list_assets()
        asset_ids = [a.id for a in assets]
        self._state.update_assets(asset_ids)
        return len(asset_ids)

    async def run_rotation(self, force: bool = False) -> dict:
        """
        Perform a single rotation: pick the next image, upload if needed,
        select on TV, set brightness.

        Returns a dict with status info for the web UI / logs.
        """
        if not self._config.schedule.enabled and not force:
            return {
                "status": "skipped",
                "reason": "schedule disabled",
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        ts = datetime.now(timezone.utc).isoformat()
        result: dict = {"status": "running", "ts": ts}

        # 1. Refresh album contents (also picks up new/removed images)
        try:
            n = await self.refresh_album()
            result["album_size"] = n
        except Exception as e:  # noqa: BLE001
            logger.error("Album refresh failed: %s", e)
            result["status"] = "error"
            result["error"] = f"album_refresh: {e}"
            return result

        if n == 0:
            result["status"] = "skipped"
            result["reason"] = "empty album"
            return result

        # 2. Advance to the next position (unless force=True means "rotate now")
        if not force:
            self._state.advance()
        else:
            # Force means: stay on current index, but re-display
            pass

        asset_id = self._state.current_asset_id()
        if not asset_id:
            result["status"] = "error"
            result["error"] = "no current asset"
            return result

        result["immich_id"] = asset_id

        # 3. Connect to the TV (with WoL if needed)
        try:
            connected = await self._frame.connect(wake_if_needed=True)
        except Exception as e:  # noqa: BLE001
            logger.error("Frame connect failed: %s", e)
            result["status"] = "error"
            result["error"] = f"frame_connect: {e}"
            return result

        if not connected:
            result["status"] = "error"
            result["error"] = "frame unreachable (WoL did not help)"
            return result

        try:
            # 4. Check if image is already uploaded
            content_id = self._state.get_uploaded(asset_id)
            if content_id:
                logger.info("Image %s already on Frame (%s) - selecting",
                            asset_id, content_id)
                result["content_id"] = content_id
                result["action"] = "select"
            else:
                # 5. Download from Immich, upload to Frame
                try:
                    img_bytes = await self._immich.download_original(asset_id)
                except Exception as e:  # noqa: BLE001
                    logger.error("Immich download failed: %s", e)
                    result["status"] = "error"
                    result["error"] = f"download: {e}"
                    return result

                content_id = await self._frame.upload(img_bytes)
                if not content_id:
                    result["status"] = "error"
                    result["error"] = "upload returned no content_id"
                    return result

                self._state.mark_uploaded(asset_id, content_id)
                result["content_id"] = content_id
                result["action"] = "upload_and_select"

            # 6. Select on TV (silent - does not wake the panel)
            ok = await self._frame.select_image(content_id, show=False)
            if not ok:
                result["status"] = "error"
                result["error"] = "select_image failed"
                return result

            # 7. Set brightness (level + disable sensor)
            b = self._config.brightness
            await self._frame.set_brightness(b.level)
            if b.disable_sensor:
                # set_brightness() already disables the sensor; this is a
                # redundant safety call in case the level-set path was skipped
                try:
                    await self._frame.set_brightness(b.level)
                except Exception:  # noqa: BLE001
                    pass

            # 8. Mark timestamp
            self._state.set_last_rotation(ts)
            result["status"] = "ok"
            return result

        finally:
            await self._frame.close()

    async def run_rotation_now(self) -> dict:
        """Force a rotation immediately (used by the manual web-UI button)."""
        return await self.run_rotation(force=True)
