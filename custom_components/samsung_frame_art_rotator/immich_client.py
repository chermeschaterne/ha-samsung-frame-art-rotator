"""
Immich API client.

Uses Immich's public share API to list album assets and download originals.
No user account / API key required.

API endpoints used (all use the share key as `?key=<shareKey>`):
  GET /api/shared-links/me             - share-link info (incl. album.id)
  GET /api/albums/<albumId>            - album metadata + asset list
  GET /api/assets/<assetId>/original   - original image bytes
  GET /api/assets/<assetId>/thumbnail  - thumbnail bytes

NOTE: The album ID is not in the share URL. It is obtained dynamically via
`/api/shared-links/me`, which returns the share metadata including the
bound album's UUID.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)


@dataclass
class ImmichAsset:
    id: str
    file_name: str
    type: str  # "IMAGE" or "VIDEO"


class ImmichError(Exception):
    """Raised for any Immich API error."""


class ImmichClient:
    def __init__(self, share_url: str, session: aiohttp.ClientSession):
        self._share_url = share_url
        self._share_key = self._extract_share_key(share_url)
        self._base_url = self._extract_base_url(share_url)
        self._session = session
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

    async def _get(self, path: str, **params) -> dict:
        url = f"{self._base_url}{path}"
        if "key" not in params:
            params["key"] = self._share_key
        try:
            async with self._session.get(url, params=params,
                                          timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status in (401, 403):
                    raise ImmichError(
                        f"Immich auth failed ({resp.status}). "
                        "Share key may be invalid, expired, or the album no longer "
                        "matches this share. Try regenerating the share link in Immich."
                    )
                if resp.status == 404:
                    raise ImmichError(f"Immich resource not found: {path}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise ImmichError(f"Immich API error {resp.status}: {body[:200]}")
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    return await resp.json()
                text = await resp.text()
                raise ImmichError(f"Expected JSON, got {ctype}: {text[:200]}")
        except aiohttp.ClientError as e:
            raise ImmichError(f"Immich request failed: {e}") from e

    async def get_shared_link_info(self) -> dict:
        """Fetch the share-link metadata via `/api/shared-links/me`."""
        data = await self._get("/api/shared-links/me")
        if not isinstance(data, dict):
            raise ImmichError("Unexpected response from /api/shared-links/me")
        return data

    async def get_album_id(self) -> str:
        """Resolve and cache the album UUID for this share."""
        if self._album_id is not None:
            return self._album_id
        info = await self.get_shared_link_info()
        share_type = info.get("type")
        if share_type != "ALBUM":
            raise ImmichError(
                f"Share link type is {share_type!r}, not 'ALBUM'. "
                "This integration requires an ALBUM-type share. "
                "Create a new share with 'Create share for album' enabled in Immich."
            )
        album = info.get("album") or {}
        album_id = album.get("id")
        if not album_id:
            raise ImmichError("Share response missing 'album.id'")
        self._album_id = album_id
        _LOGGER.info("Resolved album ID: %s (share type: %s)", album_id, share_type)
        return album_id

    async def list_assets(self, album_id: Optional[str] = None) -> List[ImmichAsset]:
        """
        List all image assets in the album.

        Uses `/api/albums/<UUID>?key=...&withoutAssets=false` to get the
        album metadata + full asset list in one call.
        """
        if album_id is None:
            album_id = await self.get_album_id()
        data = await self._get(f"/api/albums/{album_id}",
                               **{"withoutAssets": "false"})
        assets_raw = data.get("assets", [])
        result: List[ImmichAsset] = []
        for a in assets_raw:
            if a.get("type") == "IMAGE" or a.get("isImage"):
                result.append(ImmichAsset(
                    id=a["id"],
                    file_name=a.get("originalFileName", f"{a['id']}.jpg"),
                    type="IMAGE",
                ))
        _LOGGER.info("Found %d image assets in album %s", len(result), album_id)
        return result

    async def download_original(self, asset_id: str) -> bytes:
        """Download the original (unmodified) image bytes for an asset."""
        url = f"{self._base_url}/api/assets/{asset_id}/original"
        params = {"key": self._share_key}
        try:
            async with self._session.get(url, params=params,
                                          timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise ImmichError(
                        f"Failed to download asset {asset_id}: {resp.status} {body[:200]}"
                    )
                return await resp.read()
        except aiohttp.ClientError as e:
            raise ImmichError(f"Download failed for asset {asset_id}: {e}") from e
