"""
Quart web server for the HA Ingress UI.

Endpoints:
  GET  /              - Web UI (HTML)
  GET  /api/status    - JSON: current state, last/next rotation, config
  POST /api/rotate    - Trigger a manual rotation now
  POST /api/wake      - Send WoL + connect (no rotation)
  POST /api/standby   - Put TV in standby
  GET  /api/logs      - Last N log lines
  GET  /api/album     - Album asset IDs and filenames
  GET  /healthz       - Liveness probe (HA Supervisor pings this)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Optional

from hypercorn.config import Config
from hypercorn.asyncio import serve
from quart import Quart, jsonify, request, send_from_directory

from ..config import AddonConfig
from ..frame_client import FrameClient
from ..immich_client import ImmichClient
from ..rotation import RotationEngine
from ..scheduler import RotationScheduler
from ..state import StateStore

logger = logging.getLogger(__name__)

INGRESS_PORT = int(os.environ.get("INGRESS_PORT", "8099"))
LOG_BUFFER = deque(maxlen=500)  # last 500 log lines


class _WebLogHandler(logging.Handler):
    """Captures log records into a ring buffer for the /api/logs endpoint."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            LOG_BUFFER.append({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            })
        except Exception:  # noqa: BLE001
            pass


def attach_log_capture() -> None:
    """Install the in-memory log capture handler on the root logger."""
    root = logging.getLogger()
    if any(isinstance(h, _WebLogHandler) for h in root.handlers):
        return
    handler = _WebLogHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root.addHandler(handler)


def create_web_app(config: AddonConfig, state: StateStore,
                   frame: FrameClient, immich: ImmichClient,
                   rotation: RotationEngine,
                   scheduler: RotationScheduler) -> Quart:
    app = Quart(__name__, static_folder=None)

    @app.route("/")
    async def index():
        return await send_from_directory(
            str(Path(__file__).parent / "static"), "index.html"
        )

    @app.route("/static/<path:filename>")
    async def static_files(filename: str):
        return await send_from_directory(
            str(Path(__file__).parent / "static"), filename
        )

    @app.route("/healthz")
    async def healthz():
        return "ok", 200

    @app.route("/api/status")
    async def api_status():
        s = state.state
        next_run = scheduler.next_run
        return jsonify({
            "schedule_enabled": config.schedule.enabled,
            "rotation_time": config.schedule.rotation_time,
            "next_run": next_run.isoformat() if next_run else None,
            "last_rotation": s.last_rotation,
            "current_index": s.current_index,
            "album_size": len(s.asset_order),
            "current_immich_id": s.current_immich_id,
            "frame_host": config.samsung_frame.host,
            "brightness": {
                "level": config.brightness.level,
                "disable_sensor": config.brightness.disable_sensor,
                "motion_sensor": config.brightness.motion_sensor or None,
                "motion_timeout_minutes": config.brightness.motion_timeout_minutes,
            },
        })

    @app.route("/api/rotate", methods=["POST"])
    async def api_rotate():
        try:
            result = await rotation.run_rotation_now()
            return jsonify(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("Manual rotation failed")
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/api/wake", methods=["POST"])
    async def api_wake():
        try:
            connected = await frame.connect(wake_if_needed=True)
            if not connected:
                return jsonify({"status": "error", "error": "frame unreachable"}), 502
            try:
                await frame.set_art_mode(True)
            finally:
                await frame.close()
            return jsonify({"status": "ok"})
        except Exception as e:  # noqa: BLE001
            logger.exception("Wake failed")
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/api/standby", methods=["POST"])
    async def api_standby():
        try:
            connected = await frame.connect(wake_if_needed=False)
            if not connected:
                return jsonify({"status": "error", "error": "frame unreachable"}), 502
            try:
                # set_art_mode(False) puts the panel into standby (off)
                await frame.set_art_mode(False)
            finally:
                await frame.close()
            return jsonify({"status": "ok"})
        except Exception as e:  # noqa: BLE001
            logger.exception("Standby failed")
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/api/logs")
    async def api_logs():
        # Newest last (chronological for easier reading)
        return jsonify({"logs": list(LOG_BUFFER)})

    @app.route("/api/album")
    async def api_album():
        s = state.state
        return jsonify({
            "asset_order": s.asset_order,
            "uploaded": s.uploaded,
            "current_index": s.current_index,
            "current_immich_id": s.current_immich_id,
        })

    @app.errorhandler(404)
    async def not_found(_):
        return jsonify({"error": "not found"}), 404

    return app


async def run_web(app: Quart) -> None:
    """Run the Quart app via Hypercorn on the ingress port."""
    cfg = Config()
    cfg.bind = [f"0.0.0.0:{INGRESS_PORT}"]
    cfg.accesslog = None
    cfg.errorlog = None
    logger.info("Starting web server on port %d", INGRESS_PORT)
    await serve(app, cfg, shutdown_trigger=self_shutdown_trigger)


async def self_shutdown_trigger() -> None:
    """Wait for the shutdown event (placeholder for graceful shutdown)."""
    await asyncio.Event().wait()  # never fires; SIGTERM stops the process
