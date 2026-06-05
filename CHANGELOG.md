# Changelog

All notable changes to this integration are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.5] - 2026-06-05

### Added
- **`rotation_time` is now a config-flow field** (initial setup), not
  only an options-flow field. Users who expected to set the daily
  rotation time when first adding the integration no longer have to
  dive into **Configure** afterwards. The default is `06:00`; set it
  to whatever HH:MM you want.

  Behavior unchanged for existing entries: the options flow still
  takes precedence on every read, so values set there win. The options
  form also now pre-fills with the value originally entered in the
  config flow (was: fell back to the hardcoded `06:00`).

### Changed
- Added `DEFAULT_ROTATION_TIME = "06:00"` constant in `const.py`,
  used as a single source of truth for the default in both flows.
- Translated the German config-flow description in
  `translations/de.json` (was accidentally still in English).

## [1.0.4] - 2026-06-05

### Fixed
- **Blocking I/O in `__init__` of StateStore and FrameArtCoordinator**.
  Even though `_load()` / `_sync_load_token()` were sync-internal helpers,
  they were called from `__init__()`, which itself runs inside the HA
  event loop (called from `async_setup_entry`). HA logged
  `Detected blocking call to read_text` on every entry setup.

  Restructured the init flow:
  - `StateStore.__init__` no longer touches disk — defaults to an
    empty `State()`. Added `async load()` that dispatches the disk
    read to a worker thread.
  - `FrameArtCoordinator.__init__` no longer reads the saved TV token —
    constructs `FrameClient(token=None)`. Added
    `async async_load_initial_state()` that loads both state.json and
    the token in worker threads and sets `self.frame.token`.
  - `__init__.py`'s `async_setup_entry` now calls
    `await coordinator.async_load_initial_state()` between construction
    and the first coordinator refresh.

  Net effect: zero file I/O happens in the synchronous init path.

## [1.0.3] - 2026-06-05

### Fixed
- **Blocking I/O in `_save_token`**: was calling `p.write_text()` synchronously
  inside the async `_async_update_data` (HA logged `Detected blocking call to
  write_text`). Made `_save_token` / `_load_token` async, dispatching the
  file I/O to a worker thread via `asyncio.to_thread`. Kept sync internal
  helpers (`_sync_save_token` / `_sync_load_token`) for use from sync
  contexts like `__init__`.
- **Naive datetime crash on `last_rotation` sensor**: `state.py` was using
  `datetime.utcnow().isoformat() + "Z"`, which after `.rstrip("Z")` in the
  sensor became a naive datetime. HA's `timestamp` device_class sensor
  requires a tz-aware value and raised
  `ValueError: Invalid datetime: ... missing timezone information` on every
  coordinator update. Switched to `datetime.now(timezone.utc).isoformat()`
  (produces `+00:00` suffix, parses as tz-aware). Sensor now also tolerates
  legacy `Z`-suffixed values and falls back to UTC for any naive datetime.

## [1.0.2] - 2026-06-05

### Fixed
- **Setup crash**: `AttributeError: 'HomeAssistant' object has no attribute 'helpers'`.
  `hass.helpers.event.*` was removed in modern HA — now using
  `async_track_time_change` and `async_track_state_change_event` imported
  directly from `homeassistant.helpers.event`.
- **Blocking I/O in event loop**: `state.py` was calling `tmp.write_text()`
  and `tmp.replace()` synchronously inside async methods, which made HA
  log `Detected blocking call to write_text`. Converted all StateStore
  mutation methods to async, dispatching the actual file I/O to a
  worker thread via `asyncio.to_thread`.
- **NoneType errors on Frame connect**: `tv.art()` can return `None`
  instead of raising on 2023+ Frame models with polluted WebSocket
  state. `FrameClient.connect()` now treats this as a failed connect
  and logs a hint about hard-resetting the TV (unplug 3 min).

## [1.0.1] - 2026-06-05

### Fixed
- `AttributeError: 'str' object has no attribute 'exists'` during
  config-entry setup. `hass.config.path()` returns `str` in HA
  2024.4+ (not `Path` as in earlier versions). Wrapped all three
  call sites (`coordinator.state_path`, `coordinator._token_path`,
  and made `StateStore` defensive) with explicit `Path()` conversion.

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
