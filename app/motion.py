"""
Motion sensor watcher.

Optionally monitors a Home Assistant motion-sensor entity and turns
the TV off after a configurable timeout of inactivity. The TV is
put into art-mode standby (panel off, but the API remains reachable
for the next image upload).

API endpoint used:
  GET http://supervisor/core/api/states/<entity_id>
  Header: Authorization: Bearer <SUPERVISOR_TOKEN>
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_CORE_URL = os.environ.get("HA_CORE_URL", "http://supervisor/core")


class MotionWatch:
    """
    Polls a HA motion-sensor entity and invokes a callback when the
    timeout expires (no motion for N minutes).

    The callback receives a single boolean argument: True for "motion
    detected / wake the TV", False for "no motion / put TV in standby".
    """

    def __init__(self, entity_id: str, timeout_minutes: int, on_change):
        if not entity_id:
            raise ValueError("entity_id must be set")
        if timeout_minutes < 1:
            raise ValueError("timeout_minutes must be >= 1")
        self._entity_id = entity_id
        self._timeout = timeout_minutes * 60  # convert to seconds
        self._on_change = on_change
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_motion_ts: Optional[float] = None
        self._last_state: Optional[str] = None
        self._in_standby = False

    async def start(self) -> None:
        """Start the polling loop."""
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="motion-watch")
        logger.info("Motion watcher started: entity=%s, timeout=%d min",
                    self._entity_id, self._timeout // 60)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._stop.set()
        if self._task and not self._task.done():
            await asyncio.wait([self._task], timeout=3)
        self._task = None
        logger.info("Motion watcher stopped")

    async def _run(self) -> None:
        """Main loop: poll sensor every 5s, fire on_change when state changes."""
        poll_interval = 5  # seconds
        try:
            while not self._stop.is_set():
                try:
                    state = await self._fetch_state()
                    if state is not None:
                        await self._handle_state(state)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Motion poll error (continuing): %s", e)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Motion watcher crashed: %s", e)

    async def _fetch_state(self) -> Optional[str]:
        """Fetch the sensor's current state from HA Supervisor API."""
        if not SUPERVISOR_TOKEN:
            logger.debug("SUPERVISOR_TOKEN not set - cannot read HA states")
            return None
        url = f"{HA_CORE_URL}/api/states/{self._entity_id}"
        headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        logger.warning("Motion entity not found: %s", self._entity_id)
                        return None
                    if resp.status >= 400:
                        logger.debug("Motion API error %d", resp.status)
                        return None
                    data = await resp.json()
                    return str(data.get("state", "")).lower()
        except aiohttp.ClientError as e:
            logger.debug("Motion fetch network error: %s", e)
            return None

    async def _handle_state(self, state: str) -> None:
        """
        Process a state change. HA binary_sensor states are typically
        'on' (motion) or 'off' (no motion).
        """
        now = asyncio.get_event_loop().time()

        if state == "on":
            # Motion detected
            self._last_motion_ts = now
            if self._in_standby:
                logger.info("Motion detected - waking TV from standby")
                self._in_standby = False
                try:
                    await self._on_change(True)
                except Exception as e:  # noqa: BLE001
                    logger.error("on_change(True) callback failed: %s", e)
            self._last_state = state
            return

        if state != "off":
            # Unknown state - ignore
            return

        # state == "off" - no motion
        if self._last_motion_ts is None:
            # First reading, no motion yet - start the clock
            self._last_motion_ts = now
            self._last_state = state
            return

        elapsed = now - self._last_motion_ts
        if not self._in_standby and elapsed >= self._timeout:
            logger.info("No motion for %ds - putting TV in standby", int(elapsed))
            self._in_standby = True
            try:
                await self._on_change(False)
            except Exception as e:  # noqa: BLE001
                logger.error("on_change(False) callback failed: %s", e)
        self._last_state = state

    @property
    def in_standby(self) -> bool:
        return self._in_standby
