"""
Persistent state for the rotation.

Stored as JSON in the Home Assistant config directory under
`.storage/samsung_frame_art_rotator/state.json`.

Thread-safe. Atomic writes via POSIX rename.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
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
    """Thread-safe state persistence in the HA config dir."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> State:
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

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state.to_dict(), indent=2))
            tmp.replace(self._path)

    @property
    def state(self) -> State:
        return self._state

    def reset(self) -> None:
        with self._lock:
            self._state = State()
            self.save()
            _LOGGER.info("State reset to defaults")

    def update_assets(self, asset_ids: List[str]) -> bool:
        with self._lock:
            if set(asset_ids) == set(self._state.asset_order):
                return False
            self._state.asset_order = list(asset_ids)
            if self._state.current_index >= len(asset_ids):
                self._state.current_index = 0
            self.save()
            _LOGGER.info("Asset list updated: %d images", len(asset_ids))
            return True

    def advance(self) -> int:
        with self._lock:
            if not self._state.asset_order:
                return 0
            self._state.current_index = (self._state.current_index + 1) % len(self._state.asset_order)
            self.save()
            return self._state.current_index

    def current_asset_id(self) -> Optional[str]:
        with self._lock:
            if not self._state.asset_order:
                return None
            return self._state.asset_order[self._state.current_index]

    def get_uploaded(self, immich_id: str) -> Optional[str]:
        with self._lock:
            return self._state.uploaded.get(immich_id)

    def mark_uploaded(self, immich_id: str, frame_content_id: str) -> None:
        with self._lock:
            self._state.uploaded[immich_id] = frame_content_id
            self._state.current_immich_id = immich_id
            self.save()

    def set_last_rotation(self, status: str, error: Optional[str] = None) -> None:
        with self._lock:
            self._state.last_rotation = datetime.utcnow().isoformat() + "Z"
            self._state.last_rotation_status = status
            self._state.last_rotation_error = error
            self.save()
