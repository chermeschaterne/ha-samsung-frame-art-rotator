# Samsung Frame Art Rotator

A Home Assistant add-on that rotates images from an Immich shared album on a
Samsung Frame TV (Art Mode) once a day. Runs entirely on your local network;
no cloud, no subscription, no Samsung Art Store.

The add-on exposes a small web UI through HA Ingress for status, manual
control, and live log viewing.

---

## Features

- Daily rotation of images from any Immich shared album (public share link)
- Silent image updates (does not turn the TV on)
- Automatic Wake-on-LAN fallback if the TV is in deep sleep
- Built-in robustness for 2023+ Frame models (post-upload artmode, hung-recv
  timeout, KEY_POWER priming)
- Optional motion-sensor integration: standby the TV when nobody is in
  the room, wake it on motion
- Persistent state: remembers which image is "current", which images are
  already uploaded to the TV, and resumes correctly after restart
- Live web UI in the HA sidebar (status, manual buttons, logs)

---

## Installation

### 1. Add the repository to Home Assistant

In Home Assistant:

1. Go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu (top right) → **Repositories**
3. Paste this URL:

   ```
   https://github.com/chermeschaterne/ha-samsung-frame-art-rotator
   ```

4. Click **Add**, then close the dialog
5. The "Samsung Frame Art Rotator" add-on should appear under
   "Local add-ons" at the bottom of the store

### 2. Install

1. Click the add-on card → **Install**
2. Wait for the build to complete (this can take 5-10 minutes the first
   time on a Raspberry Pi as the image is built for the host architecture)

### 3. Configure

Open the **Configuration** tab. See the [Configuration](#configuration) section
below for details on each field.

### 4. Start

Go to the **Info** tab → toggle **Start on boot** → click **Start**.

The add-on takes a few seconds to start. The first rotation happens at the
configured time (default 06:00). You can also trigger a manual rotation
from the web UI (see below).

---

## Configuration

All configuration is done in the **Configuration** tab of the add-on. After
saving, restart the add-on for changes to take effect.

### Immich

| Field | Description |
|---|---|
| **Share URL** | Full URL of the Immich share link, e.g. `https://immich.example.com/share/abc123...`. Must be a public share link; no user account required. |

### Samsung Frame

| Field | Description |
|---|---|
| **Host** | IP address of the Samsung Frame on your local network. A DHCP reservation is recommended. |
| **MAC** | MAC address of the Frame, used for Wake-on-LAN. Format: `AA:BB:CC:DD:EE:FF` (lowercase accepted). |
| **Client Name** | Stable identifier the add-on uses when connecting to the TV. **Do not change after the first connection** unless you re-authorize the connection on the TV. |
| **Matte** | Frame/matte style, e.g. `flexible_apricot`, `shadowbox_warm`, `none`. See the [samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api) docs for the full list. |

### Schedule

| Field | Description |
|---|---|
| **Enabled** | Master switch. When off, no rotation happens and no connection to the TV is made. Useful for vacations or manual control. |
| **Rotation Time** | Local time of day (`HH:MM`, 24-hour) when the next image should be displayed. Default `06:00`. |

### Brightness

| Field | Description |
|---|---|
| **Level** | Art-mode brightness after each rotation. Range 1 (very dim, good for night) to 10 (max). Default `2`. |
| **Disable Sensor** | If **on**, the add-on disables the Frame's built-in ambient-light sensor and keeps brightness fixed at **Level**. If **off**, the sensor stays active and may override the configured level based on room lighting. |
| **Motion Sensor** | Optional. Entity ID of a Home Assistant motion sensor, e.g. `binary_sensor.living_room_motion`. Leave empty to disable motion-based standby. When set, the Frame is put into standby (panel off) after **Motion Timeout** minutes of no motion, and wakes on the next motion event. |
| **Motion Timeout (minutes)** | Minutes without detected motion before the Frame goes into standby. Range 1-120. Default `15`. |

---

## Web UI

After install, the **Frame Art Rotator** icon appears in the HA sidebar.
Click it to open the UI in an Ingress overlay.

The UI shows:

- **Status** — schedule on/off, next/last rotation, album size, current
  image position
- **Manual controls** — "Rotate Now", "Wake Frame", "Standby", "Refresh"
- **Configuration** — read-only view of the current values
- **Recent logs** — last 500 log lines, auto-refreshing every 10s

---

## First connection to the TV

The very first time the add-on connects to your Frame, the TV will display
a popup asking **"Allow connection from HermesFrame?"** — click **Allow**
with the TV remote. After that, the auth token is persisted in
`/data/tv_token` and the connection is automatic.

If you ever change the **Client Name** in the configuration, the TV treats
the add-on as a new device and asks again. To reset, uninstall the add-on,
delete the `/data/tv_token` file (via SSH or the HA terminal), and
re-install.

---

## How it works

1. At the configured time, the scheduler triggers a rotation
2. The add-on fetches the album's image list from Immich (via the share key)
3. It picks the next image (round-robin) and downloads the original bytes
4. The image is resized to 3840×2160 (the Frame's native resolution) and
   uploaded via the local WebSocket API
5. The image is pre-selected on the TV with `show=False` — the TV stores
   it as the "next to display" but does not turn the panel on
6. Brightness is set to the configured level and the ambient-light sensor
   is disabled
7. State (current index, upload mapping, last rotation time) is persisted
   to `/data/state.json` so a restart resumes exactly where it left off

### Silent updates

Samsung Frames have three power states:

| State | Power | API | What happens on upload |
|---|---|---|---|
| **TV on** (normal) | ~80-150W | ✅ | Image is displayed immediately |
| **Art Mode (standby)** | ~30W | ✅ | Image is queued; panel stays off |
| **Deep Sleep (off)** | ~0.5W | ❌ | No response; the add-on will send a Wake-on-LAN packet |

The add-on keeps the Frame in **Art Mode standby** for the silent-update
path. If the TV is in deep sleep, it sends a magic packet and waits up to
30 seconds for the Frame to come online.

If your TV falls into deep sleep aggressively (some Eco settings), set
**Settings → General → Eco Solution → Auto Power Off** to **Off** on the
TV itself.

---

## Uninstall

Removing the add-on is risk-free:

1. **Settings → Add-ons → Samsung Frame Art Rotator** → three-dot menu
   → **Uninstall**
2. All add-on-specific data in `/data/` is removed (state, TV token)
3. Your existing Home Assistant configuration, automations, and other
   add-ons are **not touched** in any way

To also remove the custom repository, go to the Add-on Store → ⋮ →
Repositories → delete the entry.

---

## Troubleshooting

### "Frame unreachable" error in logs

- Check that the TV is on the same network
- Verify the **Host** IP is correct (Settings → General → Network → Network
  Status on the TV)
- Verify the **MAC** address (Settings → General → Network → Network Status)
- Some routers block broadcast Wake-on-LAN between subnets; ensure the
  add-on host and the TV are on the same broadcast domain

### Rotation runs but image doesn't change

- Check the add-on log (HA → Add-on → Log tab) for upload errors
- The TV may have run out of art storage; old images can be deleted via
  the Frame's Art Mode UI (Browse Art → My Photos → select → Delete)

### Brightness keeps changing on its own

- The Frame's ambient-light sensor is fighting with the add-on. Set
  **Disable Sensor** to **on** in the add-on configuration

### Motion sensor doesn't trigger

- Verify the entity ID is correct (HA → Developer Tools → States, search
  for your motion sensor)
- The motion sensor must be a `binary_sensor` (states: `on`/`off`)
- Check the add-on log for "Motion watcher" messages

---

## Support

Issues: https://github.com/chermeschaterne/ha-samsung-frame-art-rotator/issues
