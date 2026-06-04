"""
Persistent state for the rotation.

Stored as JSON in /data/state.json (a HA-Add-on persistent volume).
The state survives container restarts and add-on updates.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path("/data/state.json")
TOKEN_FILE = Path("/data/tv_token")


@dataclass
class State:
    """Rotation state for the album."""
    current_index: int = 0
    asset_order: List[str] = field(default_factory=list)  # list of immich asset IDs
    uploaded: Dict[str, str] = field(default_factory=dict)  # immich_id -> frame content_id
    current_immich_id: Optional[str] = None
    last_rotation: Optional[str] = None  # ISO timestamp

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
        )


class StateStore:
    """Thread-safe state persistence."""

    def __init__(self, path: Path = STATE_FILE):
        self._path = path
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> State:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                logger.info("Loaded state from %s (current_index=%d, %d assets)",
                            self._path, data.get("current_index", 0),
                            len(data.get("asset_order", [])))
                return State.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load state, starting fresh: %s", e)
        return State()

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state.to_dict(), indent=2))
            tmp.replace(self._path)  # atomic on POSIX

    @property
    def state(self) -> State:
        return self._state

    def reset(self) -> None:
        """Reset state to defaults."""
        with self._lock:
            self._state = State()
            self.save()
            logger.info("State reset to defaults")

    def update_assets(self, asset_ids: List[str]) -> bool:
        """
        Update the asset list (called on each rotation).
        Returns True if the list changed (new images added/removed).
        """
        with self._lock:
            if set(asset_ids) == set(self._state.asset_order):
                return False
            self._state.asset_order = list(asset_ids)
            # If current index is out of bounds, wrap
            if self._state.current_index >= len(asset_ids):
                self._state.current_index = 0
            self.save()
            logger.info("Asset list updated: %d images", len(asset_ids))
            return True

    def advance(self) -> int:
        """Advance current_index to the next position. Returns new index."""
        with self._lock:
            if not self._state.asset_order:
                return 0
            self._state.current_index = (self._state.current_index + 1) % len(self._state.asset_order)
            self.save()
            return self._state.current_index

    def current_asset_id(self) -> Optional[str]:
        """Get the current asset ID (the one to be displayed next)."""
        with self._lock:
            if not self._state.asset_order:
                return None
            return self._state.asset_order[self._state.current_index]

    def get_uploaded(self, immich_id: str) -> Optional[str]:
        """Get the frame content_id for an already-uploaded immich asset."""
        with self._lock:
            return self._state.uploaded.get(immich_id)

    def mark_uploaded(self, immich_id: str, frame_content_id: str) -> None:
        with self._lock:
            self._state.uploaded[immich_id] = frame_content_id
            self._state.current_immich_id = immich_id
            self.save()

    def set_last_rotation(self, iso_ts: str) -> None:
        with self._lock:
            self._state.last_rotation = iso_ts
            self.save()


def load_token() -> Optional[str]:
    """Load the Samsung TV auth token, if previously saved."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip() or None
    return None


def save_token(token: str) -> None:
    """Persist the Samsung TV auth token for reuse."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    logger.info("Saved TV auth token to %s", TOKEN_FILE)
