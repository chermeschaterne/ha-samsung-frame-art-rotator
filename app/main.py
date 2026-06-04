"""
Application entry point.

Wires up all components, starts the scheduler + web server,
and handles graceful shutdown on SIGTERM/SIGINT.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from .config import load_config
from .frame_client import FrameClient
from .immich_client import ImmichClient
from .rotation import RotationEngine
from .scheduler import RotationScheduler
from .state import StateStore
from .web import attach_log_capture, create_web_app, run_web
from .motion import MotionWatch

# Ensure /data exists for state, token, and HA-Supervisor
Path("/data").mkdir(parents=True, exist_ok=True)

# Logging: to stdout (HA captures for the add-on log) and to the web capture
LOG_LEVEL = logging.INFO
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
attach_log_capture()

logger = logging.getLogger("frame-rotator")
logger.info("=== Samsung Frame Art Rotator starting ===")


async def main() -> int:
    # 1. Load and validate configuration
    try:
        config = load_config()
    except Exception as e:  # noqa: BLE001
        logger.critical("Configuration error: %s", e)
        return 1

    # 2. Initialize state store (loads from /data/state.json if present)
    state = StateStore()

    # 3. Build clients
    immich = ImmichClient(config.immich.share_url)
    frame = FrameClient(
        host=config.samsung_frame.host,
        mac=config.samsung_frame.mac,
        client_name=config.samsung_frame.client_name,
        matte=config.samsung_frame.matte,
    )

    # 4. Build rotation engine
    rotation = RotationEngine(config, state, frame, immich)

    # 5. Build scheduler
    scheduler = RotationScheduler(
        run_fn=rotation.run_rotation,
        rotation_time_str=config.schedule.rotation_time,
    )

    # 6. Web UI (Ingress)
    web_app = create_web_app(config, state, frame, immich, rotation, scheduler)

    # 7. Motion watcher (optional)
    motion: MotionWatch = None  # type: ignore
    if config.brightness.motion_sensor:
        async def on_motion_change(active: bool) -> None:
            if active:
                # Motion detected - ensure art mode is on
                try:
                    if await frame.connect(wake_if_needed=False):
                        try:
                            await frame.set_art_mode(True)
                        finally:
                            await frame.close()
                except Exception as e:  # noqa: BLE001
                    logger.error("Motion wake failed: %s", e)
            else:
                # No motion for N minutes - put in standby
                try:
                    if await frame.connect(wake_if_needed=False):
                        try:
                            await frame.set_art_mode(False)
                        finally:
                            await frame.close()
                except Exception as e:  # noqa: BLE001
                    logger.error("Motion standby failed: %s", e)
        motion = MotionWatch(
            entity_id=config.brightness.motion_sensor,
            timeout_minutes=config.brightness.motion_timeout_minutes,
            on_change=on_motion_change,
        )

    # 8. Start background tasks
    scheduler.start()
    if motion is not None:
        await motion.start()

    # Run web server in the background; main coroutine waits for shutdown
    web_task = asyncio.create_task(run_web(web_app), name="web-server")

    # 9. Wait for shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows (we don't run there but be safe)
            pass

    logger.info("Add-on ready. UI: HA sidebar -> Frame Art Rotator")
    await stop_event.wait()

    # 10. Graceful shutdown
    logger.info("Shutting down...")
    if motion is not None:
        await motion.stop()
    scheduler.stop()
    web_task.cancel()
    try:
        await web_task
    except asyncio.CancelledError:
        pass
    await immich.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
