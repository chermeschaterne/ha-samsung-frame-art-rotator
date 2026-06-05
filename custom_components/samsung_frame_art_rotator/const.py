"""Constants for the Samsung Frame Art Rotator integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "samsung_frame_art_rotator"
PLATFORMS = ["sensor", "switch", "button"]

# Config-entry keys
CONF_IMMICH_SHARE_URL = "immich_share_url"
CONF_FRAME_HOST = "frame_host"
CONF_FRAME_MAC = "frame_mac"
CONF_CLIENT_NAME = "client_name"
CONF_MATTE = "matte"
CONF_ROTATION_TIME = "rotation_time"
CONF_BRIGHTNESS_LEVEL = "brightness_level"
CONF_DISABLE_SENSOR = "disable_sensor"
CONF_MOTION_SENSOR = "motion_sensor"
CONF_MOTION_TIMEOUT = "motion_timeout_minutes"

# Defaults
DEFAULT_CLIENT_NAME = "FrameArtRotator"
DEFAULT_MATTE = "none"
DEFAULT_BRIGHTNESS_LEVEL = 2
DEFAULT_DISABLE_SENSOR = True
DEFAULT_MOTION_TIMEOUT = 15
DEFAULT_ROTATION_TIME = "06:00"

# Polling interval for the DataUpdateCoordinator (state refresh)
UPDATE_INTERVAL = timedelta(minutes=30)

# Filesystem layout (HA-relative)
TOKEN_FILE = "tv_token.json"
STATE_FILE = "state.json"
