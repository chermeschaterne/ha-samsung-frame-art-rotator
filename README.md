# Samsung Frame Art Rotator

A Home Assistant custom integration (HACS) that rotates images from an Immich
shared album on a Samsung Frame TV (Art Mode) once a day. Runs entirely inside
your Home Assistant container — no separate container, no extra services.

For installation, see **[Install](#install)** below. For configuration options,
see the in-app `Configuration → Integrations → Samsung Frame Art Rotator → Configure`
dialog (also available in German).

## Features

- Daily rotation of images from any Immich public share (no API key needed)
- Silent image updates (does not turn the TV panel on)
- Automatic Wake-on-LAN fallback if the TV is in deep sleep
- Robust WebSocket handling for 2023+ Frame models (post-upload artmode,
  hung-recv timeout, KEY_POWER priming, auth-token persistence)
- Optional motion-sensor integration: standby the TV when nobody is in
  the room, wake on motion
- Configurable brightness + ambient-light sensor disable
- Master switch in the HA sidebar (`switch.samsung_frame_rotation_enabled`)
- Live entities (sensors + buttons) you can use in HA dashboards/automations
- Persistent state in `.storage/samsung_frame_art_rotator/` (survives restart)

## Install

This is a HACS custom repository. You need HACS installed first.

### 0. Prerequisite: HACS

If you don't have HACS yet, install it in your HA container:
https://hacs.xyz/docs/setup/download (download the latest release into
`/config/custom_components/hacs/` of your HA container).

### 1. Add this repository to HACS

In Home Assistant:

1. **HACS → Integrations → ⋮ (top right) → Custom repositories**
2. **Repository:** `https://github.com/chermeschaterne/ha-samsung-frame-art-rotator`
3. **Category:** Integration
4. Click **Add**

### 2. Install

1. HACS shows the new "Samsung Frame Art Rotator" under Integrations
2. Click **Download**
3. Restart Home Assistant

### 3. Configure

1. **Settings → Devices & Services → Integrations → + Add Integration**
2. Search for **"Samsung Frame Art Rotator"**
3. Fill in:
   - **Immich share URL** — the full URL of the Immich public share
   - **Samsung Frame host** — the TV's IP address
   - **Samsung Frame MAC** — for Wake-on-LAN
   - **Client name** — leave at `FrameArtRotator` (do not change after first use)
   - **Matte** — frame style (default `none`)
   - **Rotation time** — daily HH:MM, default `06:00` (can be changed later in **Configure**)
4. Click **Submit**

### 4. Authorize the TV

The first time the integration connects to your Frame, the TV shows
**"Allow connection from FrameArtRotator?"** — click **Allow** with the TV remote.
After that, the auth token is persisted in HA's storage and reconnects
are automatic.

### 5. Verify

- The integration should appear in **Settings → Devices & Services**
- Entities: `switch.samsung_frame_rotation_enabled`, `sensor.samsung_frame_*`,
  `button.samsung_frame_rotate_now`, `button.samsung_frame_wake_frame`,
  `button.samsung_frame_standby`
- Click "Rotate now" to trigger a manual rotation immediately

## Entities created

| Entity | Type | Description |
|---|---|---|
| `switch.samsung_frame_rotation_enabled` | switch | Master switch — turn off to pause all rotations |
| `sensor.samsung_frame_album_size` | sensor | Number of images in the album |
| `sensor.samsung_frame_current_image` | sensor | Current Immich asset ID |
| `sensor.samsung_frame_next_rotation` | timestamp | When the next scheduled rotation happens |
| `sensor.samsung_frame_last_rotation` | timestamp | When the last rotation ran |
| `sensor.samsung_frame_last_rotation_status` | sensor | "ok" / "error" / "skipped" with error details in attributes |
| `button.samsung_frame_rotate_now` | button | Trigger a manual rotation |
| `button.samsung_frame_wake_frame` | button | WoL + enable art mode |
| `button.samsung_frame_standby` | button | Disable art mode (panel off) |

## Services

You can also trigger the actions from HA automations:

```yaml
action:
  - service: samsung_frame_art_rotator.rotate
```

Available services: `samsung_frame_art_rotator.rotate`, `...wake`, `...standby`.

## Configuration options (after initial setup)

After the integration is set up, go to
**Settings → Devices & Services → Samsung Frame Art Rotator → Configure**
to change runtime settings without re-creating the integration:

- **Master switch** — pause all rotations
- **Rotation time** — daily HH:MM
- **Brightness level** — 1 (very dim) to 10 (max), default 2
- **Disable ambient sensor** — keep brightness fixed (recommended for art)
- **Motion sensor** — optional entity_id of a HA motion sensor
- **Motion timeout** — minutes without motion before the TV goes to standby

## Uninstall

Completely risk-free:

1. **Settings → Devices & Services → Samsung Frame Art Rotator → ⋮ → Delete**
2. **HACS → Integrations → Samsung Frame Art Rotator → ⋮ → Remove**
3. Optionally delete the repo from HACS Custom Repositories
4. Optionally delete `.storage/samsung_frame_art_rotator/` from your HA config dir

Your other integrations, automations, and devices are **not touched** in any
way. The TV's stored art is also untouched (you can delete it manually via
the Frame's UI if desired).

## License

MIT — see [LICENSE](LICENSE).
