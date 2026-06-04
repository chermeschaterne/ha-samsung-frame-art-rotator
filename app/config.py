"""
Configuration loader for the add-on.

Reads /data/options.json (written by the Home Assistant Supervisor)
and validates it against a Pydantic schema.

All times are in the local timezone configured on the HA host.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

OPTIONS_FILE = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))


class ImmichConfig(BaseModel):
    share_url: str = Field(..., description="Full Immich share URL")

    @field_validator("share_url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("share_url must be an http(s) URL")
        if "/share/" not in v:
            raise ValueError("share_url must contain '/share/' (Immich share link)")
        return v.rstrip("/")


class SamsungFrameConfig(BaseModel):
    host: str = Field(..., description="IP address of the Samsung Frame")
    mac: str = Field(..., description="MAC address for Wake-on-LAN")
    client_name: str = Field(default="HermesFrame", description="Stable client identifier")
    matte: str = Field(default="none", description="Frame matte (style_color)")

    @field_validator("host")
    @classmethod
    def _valid_host(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) != 4:
            raise ValueError("host must be an IPv4 address")
        try:
            if not all(0 <= int(p) <= 255 for p in parts):
                raise ValueError
        except ValueError:
            raise ValueError("host must be a valid IPv4 address") from None
        return v

    @field_validator("mac")
    @classmethod
    def _valid_mac(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 6 or not all(len(p) == 2 for p in parts):
            raise ValueError("mac must be in format AA:BB:CC:DD:EE:FF")
        return v.lower()


class ScheduleConfig(BaseModel):
    enabled: bool = Field(default=True, description="Master switch for rotation")
    rotation_time: str = Field(default="06:00", description="Daily rotation time HH:MM")

    @field_validator("rotation_time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        try:
            hh, mm = v.split(":")
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("rotation_time must be in HH:MM format") from None
        return f"{int(hh):02d}:{int(mm):02d}"


class BrightnessConfig(BaseModel):
    level: int = Field(default=2, ge=1, le=10, description="Brightness level 1-10")
    disable_sensor: bool = Field(default=True, description="Disable ambient light sensor")
    motion_sensor: str = Field(default="", description="Optional motion sensor entity_id")
    motion_timeout_minutes: int = Field(default=15, ge=1, le=120,
                                          description="Minutes without motion before standby")


class AddonConfig(BaseModel):
    immich: ImmichConfig
    samsung_frame: SamsungFrameConfig
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    brightness: BrightnessConfig = Field(default_factory=BrightnessConfig)


def load_config() -> AddonConfig:
    """Load and validate configuration from /data/options.json."""
    if not OPTIONS_FILE.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {OPTIONS_FILE}. "
            "Make sure the add-on is properly configured in HA."
        )

    raw = json.loads(OPTIONS_FILE.read_text())
    cfg = AddonConfig(**raw)
    logger.info("Configuration loaded successfully")
    logger.info("  Immich share URL: %s", cfg.immich.share_url)
    logger.info("  Samsung Frame:    %s (MAC %s)", cfg.samsung_frame.host, cfg.samsung_frame.mac)
    logger.info("  Schedule:         enabled=%s, time=%s",
                cfg.schedule.enabled, cfg.schedule.rotation_time)
    logger.info("  Brightness:       level=%d, disable_sensor=%s, motion_sensor=%s",
                cfg.brightness.level, cfg.brightness.disable_sensor,
                cfg.brightness.motion_sensor or "(none)")
    return cfg
