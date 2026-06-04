"""
Samsung Frame TV client.

Wraps `samsungtvws` (the local WebSocket API) with all the robustness
patterns discovered in production:

  - Wake-on-LAN fallback if TV is in deep sleep
  - KEY_POWER priming to unblock the art WebSocket
  - robust_call() exception-based retry (timeouts, connection drops)
  - _with_timeout() daemon-thread hard cutoff (hung recv() protection)
  - Post-upload artmode structure (NOT before upload)
  - Token persistence in /data/tv_token
  - Silent image updates (show=False) so the panel does not wake

Reference pitfalls from the samsung-frame-art skill are all encoded here.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import socket
import struct
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from PIL import Image
from samsungtvws import SamsungTVWS
from samsungtvws.exceptions import ConnectionFailure

from .state import load_token, save_token

logger = logging.getLogger(__name__)

FRAME_W, FRAME_H = 3840, 2160


# ----------------------------------------------------------------------------
# Robustness helpers
# ----------------------------------------------------------------------------

def _with_timeout(func, *args, timeout: float = 12, **kwargs):
    """
    Run a sync function in a daemon thread with a hard wall-clock deadline.

    Why: On 2023+ Frame models, socket.recv() can block indefinitely after
    heavy operations (no exception, no timeout fires). A thread-based
    deadline is the only reliable way to escape that state.

    Returns (value, exception). If timeout fires, returns (None, TimeoutError).
    """
    result: list = [None, None]

    def runner():
        try:
            result[0] = func(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            result[1] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        # Daemon thread is still running - it will die with the process.
        return None, TimeoutError(f"call exceeded {timeout}s wall-clock budget")
    return result[0], result[1]


def robust_call(func, *args, max_attempts: int = 2, retry_delay: float = 2.5,
                timeout: float = 12, **kwargs):
    """
    Call func with retry on exception AND a hard timeout per attempt.

    The WebSocketTimeoutException retry pattern works because samsungtvws
    re-opens the WebSocket internally on the next send_command call, so a
    short delay then retry usually succeeds.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            value, exc = _with_timeout(func, *args, timeout=timeout, **kwargs)
            if exc is None:
                if attempt > 1:
                    logger.info("robust_call succeeded on attempt %d", attempt)
                return value
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                logger.warning("robust_call attempt %d: timed out after %.1fs",
                               attempt, timeout)
            else:
                logger.warning("robust_call attempt %d: %s: %s",
                               attempt, type(exc).__name__, exc)
            last_exc = exc
        except (ConnectionFailure, ConnectionError, OSError) as e:
            logger.warning("robust_call attempt %d: %s: %s",
                           attempt, type(e).__name__, e)
            last_exc = e
        if attempt < max_attempts:
            time.sleep(retry_delay)
    raise last_exc if last_exc else RuntimeError("robust_call: all attempts failed")


# ----------------------------------------------------------------------------
# Wake-on-LAN
# ----------------------------------------------------------------------------

def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> bool:
    """
    Send a Wake-on-LAN magic packet to the given MAC address.

    The packet is broadcast on the local network; the TV's network card
    listens for it in deep sleep and powers on the device.
    """
    mac_clean = mac.replace(":", "").replace("-", "").lower()
    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC for WoL: {mac!r}")
    try:
        mac_bytes = bytes.fromhex(mac_clean)
    except ValueError as e:
        raise ValueError(f"Invalid hex in MAC {mac!r}: {e}") from None

    # Magic packet: 6 bytes 0xFF + 16 repetitions of the MAC
    packet = b"\xff" * 6 + mac_bytes * 16

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()
    logger.info("Sent Wake-on-LAN packet to %s (broadcast %s:%d)", mac, broadcast, port)
    return True


# ----------------------------------------------------------------------------
# Image preparation
# ----------------------------------------------------------------------------

def resize_for_frame(input_bytes: bytes, output_path: str = "/tmp/frame_upload.jpg",
                     target: tuple = (FRAME_W, FRAME_H),
                     quality: int = 92) -> str:
    """
    Resize an arbitrary image to 3840x2160 JPEG, preserving aspect ratio
    by letterboxing/cropping to fit.

    Returns the output file path.
    """
    img = Image.open(io.BytesIO(input_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    target_w, target_h = target
    ratio = img.width / img.height
    target_ratio = target_w / target_h

    if ratio > target_ratio:
        # Image is wider - fit width, then crop height
        new_w = target_w
        new_h = int(target_w / ratio)
    else:
        new_h = target_h
        new_w = int(target_h * ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center-crop to exact target dimensions
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    if left or top or new_w != target_w or new_h != target_h:
        img = img.crop((left, top, left + target_w, top + target_h))

    img.save(output_path, "JPEG", quality=quality)
    logger.info("Resized image to %dx%d -> %s", target_w, target_h, output_path)
    return output_path


# ----------------------------------------------------------------------------
# Main client
# ----------------------------------------------------------------------------

class FrameClient:
    """
    High-level client for Samsung Frame art operations.

    Usage:
        client = FrameClient(host="192.168.2.92", mac="...", token="...")
        await client.connect()
        content_id = await client.upload(image_bytes)
        await client.select_image(content_id)
        await client.set_brightness(2)
        await client.close()
    """

    def __init__(self, host: str, mac: str, client_name: str = "HermesFrame",
                 matte: str = "none", token: Optional[str] = None,
                 port: int = 8002):
        self.host = host
        self.mac = mac
        self.client_name = client_name
        self.matte = matte
        self.port = port
        self._token = token or load_token()
        self._tv: Optional[SamsungTVWS] = None
        self._art = None

    def _new_tv(self) -> SamsungTVWS:
        """Create a fresh TV client with current token (long timeout for upload)."""
        tv = SamsungTVWS(
            host=self.host,
            port=self.port,
            token=self._token,
            timeout=30,  # 4K JPEG upload can take 15-25s on stable LAN
            name=self.client_name,
        )
        return tv

    def _is_reachable(self, timeout: float = 3.0) -> bool:
        """Check if the TV's WebSocket port is reachable."""
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    async def connect(self, wake_if_needed: bool = True) -> bool:
        """
        Establish WebSocket connection. If TV is unreachable, attempt WoL.

        Returns True if connected, False if unreachable after WoL.
        """
        if not self._is_reachable():
            if not wake_if_needed:
                logger.warning("Frame %s:%d not reachable", self.host, self.port)
                return False
            logger.info("Frame not reachable - sending Wake-on-LAN")
            try:
                send_wol(self.mac)
            except Exception as e:  # noqa: BLE001
                logger.warning("WoL failed: %s", e)
            # Give the TV time to power on
            for _ in range(15):
                await asyncio.sleep(2)
                if self._is_reachable():
                    logger.info("Frame reachable after WoL")
                    break
            else:
                logger.error("Frame still unreachable after WoL")
                return False

        # Connect (with one retry, since the WebSocket can flake on first try)
        for attempt in range(2):
            try:
                self._tv = await asyncio.to_thread(self._new_tv)
                # First-time auth: SamsungTVWS does not expose an async open;
                # the library opens on first art() call.
                break
            except (ConnectionFailure, OSError, asyncio.TimeoutError) as e:
                logger.warning("TV init attempt %d: %s", attempt + 1, e)
                if attempt == 1:
                    return False
                await asyncio.sleep(2)

        # Prime the connection by sending a remote key - this unblocks the
        # art WebSocket on 2023+ models (see pitfall #9 in samsung-frame-art skill)
        try:
            await asyncio.to_thread(self._prime_connection)
        except Exception as e:  # noqa: BLE001
            logger.debug("KEY_POWER priming failed (non-fatal): %s", e)

        # Get art handle
        try:
            self._art = await asyncio.to_thread(self._tv.art)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to obtain art handle: %s", e)
            return False

        # Persist any newly issued token
        if self._tv.token and self._tv.token != self._token:
            self._token = self._tv.token
            try:
                save_token(self._tv.token)
                logger.info("Persisted new TV auth token")
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not persist token: %s", e)

        return True

    def _prime_connection(self) -> None:
        """Send a remote key to wake the art WebSocket subsystem."""
        if self._tv is None:
            return
        try:
            remote = self._tv.remote()
            remote.send_key("KEY_POWER")
        except Exception:  # noqa: BLE001
            pass  # Best effort

    async def is_in_art_mode(self) -> bool:
        """Return True if the Frame is currently in art mode."""
        if self._art is None:
            return False
        try:
            value, exc = await asyncio.to_thread(
                _with_timeout,
                self._art.get_artmode, timeout=8,
            )
            if exc is not None:
                logger.debug("get_artmode error: %s", exc)
                return False
            return str(value).lower() == "on"
        except Exception as e:  # noqa: BLE001
            logger.debug("is_in_art_mode error: %s", e)
            return False

    async def upload(self, image_bytes: bytes) -> Optional[str]:
        """
        Upload an image to the Frame. Returns the content_id, or None on failure.

        The image is resized to 3840x2160 first. The upload is retried once
        on WebSocketTimeoutException (see samsung-frame-art pitfall #8).
        """
        if self._art is None:
            logger.error("upload() called before connect()")
            return None

        # Resize in a thread (PIL is CPU-bound, but we're already async)
        try:
            path = await asyncio.to_thread(resize_for_frame, image_bytes)
        except Exception as e:  # noqa: BLE001
            logger.error("Image resize failed: %s", e)
            return None

        # Upload - this is the legitimate long path (15-25s for 4K JPEG).
        # We do NOT apply the hard _with_timeout cutoff here; that would
        # corrupt TV state if the upload actually succeeded. Instead we use
        # exception-based retry (WebSocketTimeoutException is raised cleanly).
        def do_upload():
            with open(path, "rb") as f:
                data = f.read()
            return self._art.upload(data, file_type="JPEG", matte=self.matte,
                                    portrait_matte=self.matte)

        try:
            content_id = await asyncio.to_thread(robust_call, do_upload,
                                                 max_attempts=2, retry_delay=3.0,
                                                 timeout=60)
            if isinstance(content_id, dict):
                content_id = content_id.get("content_id") or content_id.get("id")
            logger.info("Uploaded to Frame, content_id=%s", content_id)
            return str(content_id) if content_id else None
        except Exception as e:  # noqa: BLE001
            logger.error("Upload failed: %s", e)
            return None

    async def select_image(self, content_id: str, show: bool = False) -> bool:
        """
        Select (and optionally show) an image.

        With show=False the image is pre-selected but NOT displayed yet -
        this is the silent path for scheduled rotation while the TV is in
        art-mode standby. show=True forces immediate display.
        """
        if self._art is None:
            return False

        def do_select():
            return self._art.select_image(content_id, show=show)

        try:
            await asyncio.to_thread(robust_call, do_select,
                                    max_attempts=2, retry_delay=2.0, timeout=10)
            logger.info("Selected image %s (show=%s)", content_id, show)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("select_image failed: %s", e)
            return False

    async def set_art_mode(self, on: bool = True) -> bool:
        """
        Enable/disable art mode.

        Per pitfall #1 in the skill: art mode is more reliable AFTER upload.
        Wrap in robust_call to handle WebSocket flakes.
        """
        if self._art is None:
            return False

        def do_set():
            return self._art.set_artmode(on)

        try:
            await asyncio.to_thread(robust_call, do_set,
                                    max_attempts=2, retry_delay=2.0, timeout=10)
            logger.info("Set art mode = %s", on)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("set_artmode failed: %s", e)
            return False

    async def set_brightness(self, level: int) -> bool:
        """Set art-mode brightness to the given level (1-10)."""
        if self._art is None:
            return False
        level = max(1, min(10, level))

        def do_brightness():
            return self._art.set_brightness(level)

        def do_sensor_off():
            return self._art.set_brightness_sensor_setting(False)

        ok1 = ok2 = False
        try:
            await asyncio.to_thread(robust_call, do_brightness,
                                    max_attempts=2, retry_delay=2.0, timeout=10)
            ok1 = True
        except Exception as e:  # noqa: BLE001
            logger.error("set_brightness failed: %s", e)
        try:
            await asyncio.to_thread(robust_call, do_sensor_off,
                                    max_attempts=2, retry_delay=2.0, timeout=10)
            ok2 = True
        except Exception as e:  # noqa: BLE001
            logger.error("set_brightness_sensor_setting failed: %s", e)
        if ok1 and ok2:
            logger.info("Set brightness to %d (sensor disabled)", level)
        return ok1 and ok2

    async def list_available(self) -> list:
        """List all art currently on the Frame (newest first)."""
        if self._art is None:
            return []

        def do_list():
            return self._art.available()

        try:
            return await asyncio.to_thread(robust_call, do_list,
                                           max_attempts=2, retry_delay=2.0, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.error("available() failed: %s", e)
            return []

    async def close(self) -> None:
        """Cleanly close the WebSocket connection."""
        if self._tv is not None:
            try:
                await asyncio.to_thread(self._tv.close)
            except Exception:  # noqa: BLE001
                pass
            self._tv = None
            self._art = None
