# Changelog

All notable changes to this integration are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-04

### Added
- Initial HACS custom integration release
- Daily rotation of Immich shared album images on Samsung Frame TV
- Silent image updates (does not wake the TV panel)
- Wake-on-LAN fallback if the Frame is in deep sleep
- Robust WebSocket handling for 2023+ Frame models (post-upload artmode,
  hung-recv timeout, KEY_POWER priming, auth-token persistence)
- Optional motion-sensor-based standby (HA native state polling)
- Configurable brightness level + ambient-light sensor disable
- Master switch, sensors, and 3 buttons as HA entities
- Daily-rotation scheduler via HA's `async_track_time_change`
- Config-flow with schema validation
- English + German UI strings
- Persistent state in HA's `.storage/` (survives restart)
- Multi-platform support: works in any HA Docker container (no Supervisor
  required, since this is a HACS integration not an Add-on)
