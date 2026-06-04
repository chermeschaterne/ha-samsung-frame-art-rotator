"""
Immich API client.

Uses Immich's public share API to list album assets and download originals.
No user account / API key required.

Share URL format: https://<host>/share/<shareKey>

API endpoints used (all use the share key as `?key=<shareKey>`):
  GET /api/albums/<albumId>            - album metadata (incl. asset IDs)
  GET /api/assets/<assetId>/original   - original image bytes

NOTE: The album ID is not in the share URL - we get it by listing
shared albums via GET /api/albums?key=<shareKey>.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class ImmichAsset:
    id: str
    file_name: str
    type: str  # "IMAGE" or "VIDEO"


class ImmichError(Exception):
    """Raised for any Immich API error."""


class ImmichClient:
    def __init__(self, share_url: str, session: Optional[aiohttp.ClientSession] = None):
        self._share_url = share_url
        self._share_key = self._extract_share_key(share_url)
        self._base_url = self._extract_base_url(share_url)
        self._session = session
        self._owned_session = session is None
        # Lazy-loaded on first use
        self._album_id: Optional[str] = None

    @staticmethod
    def _extract_share_key(url: str) -> str:
        """Extract the share key (last URL segment after /share/)."""
        m = re.search(r"/share/([^/?#]+)", url)
        if not m:
            raise ImmichError(f"Invalid Immich share URL (no /share/ segment): {url}")
        return m.group(1)

    @staticmethod
    def _extract_base_url(url: str) -> str:
        """Extract scheme + host (no path)."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def share_key(self) -> str:
        return self._share_key

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)
            )
            self._owned_session = True
        return self._session

    async def close(self) -> None:
        if self._owned_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get(self, path: str, **params) -> dict:
        session = await self._ensure_session()
        url = f"{self._base_url}{path}"
        if "key" not in params:
            params["key"] = self._share_key
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise ImmichError(
                        f"Immich auth failed ({resp.status}). "
                        "Share key may be invalid or expired."
                    )
                if resp.status == 404:
                    raise ImmichError(f"Immich resource not found: {path}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise ImmichError(f"Immich API error {resp.status}: {body[:200]}")
                return await resp.json()
        except aiohttp.ClientError as e:
            raise ImmichError(f"Immich request failed: {e}") from e

    async def list_albums(self) -> List[dict]:
        """List all shared albums accessible via this share key."""
        data = await self._get("/api/albums")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "albums" in data:
            return data["albums"]
        # Some Immich versions wrap differently
        if isinstance(data, dict):
            return [data]
        return []

    async def get_first_album_id(self) -> str:
        """Get the first (or only) shared album ID for this share key."""
        if self._album_id is not None:
            return self._album_id
        albums = await self.list_albums()
        if not albums:
            raise ImmichError(
                f"No shared albums found for share key. "
                f"Check that the Immich share URL is correct and the album is still shared."
            )
        # If multiple, use the first one (the share URL was for a specific album)
        album_id = albums[0].get("id")
        if not album_id:
            raise ImmichError("Immich album response missing 'id' field")
        self._album_id = album_id
        logger.info("Resolved album ID: %s", album_id)
        return album_id

    async def get_album_info(self, album_id: Optional[str] = None) -> dict:
        if album_id is None:
            album_id = await self.get_first_album_id()
        return await self._get(f"/api/albums/{album_id}")

    async def list_assets(self, album_id: Optional[str] = None) -> List[ImmichAsset]:
        """List all image assets in the album."""
        if album_id is None:
            album_id = await self.get_first_album_id()
        info = await self.get_album_info(album_id)
        assets_raw = info.get("assets", [])
        result: List[ImmichAsset] = []
        for a in assets_raw:
            # Filter to images only (skip videos - Samsung Frame can show them
            # but they're not part of the typical art rotation use case)
            if a.get("type") == "IMAGE" or a.get("isImage"):
                result.append(ImmichAsset(
                    id=a["id"],
                    file_name=a.get("originalFileName", f"{a['id']}.jpg"),
                    type="IMAGE",
                ))
        logger.info("Found %d image assets in album %s", len(result), album_id)
        return result

    async def download_original(self, asset_id: str) -> bytes:
        """Download the original (unmodified) image bytes for an asset."""
        session = await self._ensure_session()
        url = f"{self._base_url}/api/assets/{asset_id}/original"
        params = {"key": self._share_key}
        try:
            async with session.get(url, params=params) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise ImmichError(
                        f"Failed to download asset {asset_id}: {resp.status} {body[:200]}"
                    )
                return await resp.read()
        except aiohttp.ClientError as e:
            raise ImmichError(f"Download failed for asset {asset_id}: {e}") from e
