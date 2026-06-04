# Changelog

All notable changes to this add-on are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-04

### Added
- Initial release
- Daily rotation of Immich shared album images on Samsung Frame TV
- Silent image updates (does not wake the TV panel)
- Wake-on-LAN fallback if the Frame is in deep sleep
- Robust WebSocket handling for 2023+ Frame models (post-upload artmode,
  hung-recv timeout, KEY_POWER priming, auth-token persistence)
- Optional motion-sensor-based standby (HA Supervisor API)
- Configurable brightness level + ambient-light sensor disable
- Master switch to enable/disable the rotation schedule
- Web UI via HA Ingress (status, manual controls, live logs)
- Multi-architecture support: aarch64, amd64, armv7, armhf, i386
- Persistent state (current index, upload mapping, last rotation)
- Atomic state file writes (POSIX rename)
