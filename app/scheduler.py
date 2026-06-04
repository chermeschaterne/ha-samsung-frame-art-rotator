"""
APScheduler wrapper for the daily rotation cron.

Schedules `run_rotation` at the configured HH:MM in the local timezone.
The scheduler runs as a background asyncio task.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class RotationScheduler:
    def __init__(self, run_fn: Callable[[], Awaitable[dict]],
                 rotation_time_str: str, timezone: str = "Europe/Berlin"):
        self._run_fn = run_fn
        self._time_str = rotation_time_str
        self._timezone = timezone
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job = None
        self._next_run: Optional[datetime] = None

    def start(self) -> None:
        """Start the scheduler with a daily cron job at the configured time."""
        if self._scheduler is not None:
            return
        hh, mm = self._time_str.split(":")
        self._scheduler = AsyncIOScheduler(timezone=self._timezone)
        self._job = self._scheduler.add_job(
            self._wrapped_run,
            CronTrigger(hour=int(hh), minute=int(mm), timezone=self._timezone),
            id="frame_rotation",
            name="Daily Frame Art Rotation",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        # Cache the next-run time for the web UI
        try:
            self._next_run = self._job.next_run_time
        except Exception:  # noqa: BLE001
            self._next_run = None
        logger.info("Scheduler started: daily at %s %s", self._time_str, self._timezone)

    def stop(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
            self._scheduler = None
            self._job = None
            logger.info("Scheduler stopped")

    async def _wrapped_run(self) -> None:
        logger.info("=== Scheduled rotation starting ===")
        try:
            result = await self._run_fn()
            logger.info("Scheduled rotation result: %s", result.get("status"))
        except Exception as e:  # noqa: BLE001
            logger.exception("Scheduled rotation failed: %s", e)
        # Update next-run cache
        try:
            if self._job is not None:
                self._next_run = self._job.next_run_time
        except Exception:  # noqa: BLE001
            pass

    def update_time(self, new_time_str: str) -> None:
        """Change the rotation time and restart the job."""
        self.stop()
        self._time_str = new_time_str
        self.start()

    @property
    def next_run(self) -> Optional[datetime]:
        try:
            if self._job is not None:
                return self._job.next_run_time
        except Exception:  # noqa: BLE001
            pass
        return self._next_run
