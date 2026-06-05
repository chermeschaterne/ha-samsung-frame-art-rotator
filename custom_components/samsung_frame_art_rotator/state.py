"""
Persistent state for the rotation.

Stored as JSON in the Home Assistant config directory under
`.storage/samsung_frame_art_rotator/state.json`.

Thread-safe + asyncio-safe. All file I/O is dispatched to a worker
thread via `asyncio.to_thread` so the HA event loop is never blocked
(`Detected blocking call to write_text` warnings).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class State:
    """Rotation state for the album."""
    current_index: int = 0
    asset_order: List[str] = field(default_factory=list)  # list of immich asset IDs
    uploaded: Dict[str, str] = field(default_factory=dict)  # immich_id -> frame content_id
    current_immich_id: Optional[str] = None
    last_rotation: Optional[str] = None  # ISO timestamp
    last_rotation_status: Optional[str] = None  # "ok" | "error" | "skipped"
    last_rotation_error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        return cls(
            current_index=d.get("current_index", 0),
            asset_order=d.get("asset_order", []),
            uploaded=d.get("uploaded", {}),
            current_immich_id=d.get("current_immich_id"),
            last_rotation=d.get("last_rotation"),
            last_rotation_status=d.get("last_rotation_status"),
            last_rotation_error=d.get("last_rotation_error"),
        )


class StateStore:
    """Async, thread-safe state persistence in the HA config dir.

    All mutation methods are `async` and dispatch the blocking file I/O
    to a worker thread via `asyncio.to_thread`. Read methods stay sync
    (they only touch in-memory state). The threading.RLock is kept so
    the worker-thread code and any direct sync readers stay consistent.
    """

    def __init__(self, path: Path | str):
        # Accept str or Path defensively — `hass.config.path()` returns
        # str in HA 2024.4+ but Path in earlier versions. Normalize here
        # so callers don't have to remember to wrap.
        # NO file I/O here — `__init__` runs inside the HA event loop
        # when called from `async_setup_entry`. The caller must
        # `await state_store.load()` explicitly after construction.
        self._path = Path(path)
        self._lock = threading.RLock()
        self._state = State()  # default; populated by `await load()`

    # --- sync I/O (always called via asyncio.to_thread) ---

    def _sync_load(self) -> State:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                _LOGGER.info("Loaded state from %s (current_index=%d, %d assets)",
                             self._path, data.get("current_index", 0),
                             len(data.get("asset_order", [])))
                return State.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                _LOGGER.warning("Failed to load state, starting fresh: %s", e)
        return State()

    def _sync_save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state.to_dict(), indent=2))
            tmp.replace(self._path)

    def _sync_reset(self) -> None:
        with self._lock:
            self._state = State()
            self._sync_save()
            _LOGGER.info("State reset to defaults")

    def _sync_update_assets(self, asset_ids: List[str]) -> bool:
        with self._lock:
            if set(asset_ids) == set(self._state.asset_order):
                return False
            self._state.asset_order = list(asset_ids)
            if self._state.current_index >= len(asset_ids):
                self._state.current_index = 0
            self._sync_save()
            _LOGGER.info("Asset list updated: %d images", len(asset_ids))
            return True

    def _sync_advance(self) -> int:
        with self._lock:
            if not self._state.asset_order:
                return 0
            self._state.current_index = (
                self._state.current_index + 1
            ) % len(self._state.asset_order)
            self._sync_save()
            return self._state.current_index

    def _sync_mark_uploaded(self, immich_id: str,
                            frame_content_id: str) -> None:
        with self._lock:
            self._state.uploaded[immich_id] = frame_content_id
            self._state.current_immich_id = immich_id
            self._sync_save()

    def _sync_set_last_rotation(self, status: str,
                                error: Optional[str]) -> None:
        with self._lock:
            # Use timezone-aware UTC so `datetime.fromisoformat(...)` in
            # the sensor layer returns a tz-aware datetime. HA's
            # `timestamp` device_class sensor requires a timezone-aware
            # value and rejects naive datetimes with ValueError.
            # Note: `datetime.utcnow()` is deprecated in Python 3.12+
            # and also produces a naive datetime — use now(timezone.utc).
            self._state.last_rotation = datetime.now(timezone.utc).isoformat()
            self._state.last_rotation_status = status
            self._state.last_rotation_error = error
            self._sync_save()

    # --- async public API (dispatch to thread) ---

    async def load(self) -> None:
        """Load state from disk in a worker thread.

        Must be awaited once after construction (typically from
        `async_setup_entry`). After this returns, `state` is safe
        to read sync; all writes go through `save()` which dispatches
        to a thread.
        """
        try:
            self._state = await asyncio.to_thread(self._sync_load)
        except OSError as e:
            _LOGGER.warning("Failed to read state file: %s", e)
            self._state = State()

    async def save(self) -> None:
        """Persist current state to disk in a worker thread."""
        await asyncio.to_thread(self._sync_save)

    async def reset(self) -> None:
        await asyncio.to_thread(self._sync_reset)

    async def update_assets(self, asset_ids: List[str]) -> bool:
        return await asyncio.to_thread(self._sync_update_assets, list(asset_ids))

    async def advance(self) -> int:
        return await asyncio.to_thread(self._sync_advance)

    async def mark_uploaded(self, immich_id: str,
                            frame_content_id: str) -> None:
        await asyncio.to_thread(
            self._sync_mark_uploaded, immich_id, frame_content_id
        )

    async def set_last_rotation(self, status: str,
                                error: Optional[str] = None) -> None:
        await asyncio.to_thread(self._sync_set_last_rotation, status, error)

    # --- sync read API (no I/O, safe to call from anywhere) ---

    @property
    def state(self) -> State:
        return self._state

    def current_asset_id(self) -> Optional[str]:
        with self._lock:
            if not self._state.asset_order:
                return None
            return self._state.asset_order[self._state.current_index]

    def get_uploaded(self, immich_id: str) -> Optional[str]:
        with self._lock:
            return self._state.uploaded.get(immich_id)
