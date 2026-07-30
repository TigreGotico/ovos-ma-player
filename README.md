# ovos-ma-player

Music Assistant PlayerProvider that drives a **local** OpenVoiceOS (OVOS) instance through the
OCP (OpenVoiceOS Common Play) messagebus protocol.

Music Assistant resolves a stream URL and hands it to OVOS/OCP using standard OCP bus messages.
OVOS handles the actual audio pipeline; state changes are pushed back to MA via
`ovos.common_play.player.state` events and backed up by a polling fallback.

---

## Background: What is Music Assistant?

> If you already know what Music Assistant is, skip this section.

[Music Assistant](https://music-assistant.io) (MA) is a self-hosted media server that aggregates
music from many sources (Spotify, YouTube Music, local files, and more) and streams it to
players around your home. It runs as a server process (standalone or inside a Home Assistant
add-on) and exposes a web UI plus a WebSocket API. "Player providers" are plugins that teach MA
how to send audio to a specific type of playback device. This package is one such plugin.

## Background: What is OVOS and OCP?

> If you already know OVOS and OCP, skip this section.

[OpenVoiceOS](https://openvoiceos.org) (OVOS) is an open-source voice assistant platform: a
community fork and evolution of the original Mycroft AI assistant. It runs on Linux (commonly on
a Raspberry Pi) and listens for a wake word, then processes spoken commands through a pipeline of
skills. All internal communication happens over a local WebSocket called the **messagebus**
(`ws://localhost:8181/core`), where every event is a JSON message with a `type` and a `data` dict.

**OCP** (OpenVoiceOS Common Play) is the audio subsystem inside OVOS. It is implemented as a
skill/plugin and manages everything audio-related: queuing tracks, controlling the audio backend
(VLC, mpd, etc.), and surfacing playback state on the bus. Skills that want to play audio post
`ovos.common_play.play` messages; anything that wants to know what is playing subscribes to
`ovos.common_play.player.state`. This plugin speaks that same protocol, so from OVOS's point of
view, Music Assistant looks like another OCP skill.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Required by both MA and this plugin |
| Music Assistant | The server that this plugin extends |
| OVOS with OCP | Must be running on the same host or reachable LAN IP. OCP is included in standard OVOS installations. |
| OVOS messagebus accessible | `ws://host:8181/core` must be reachable from MA with no authentication |

OVOS and Music Assistant do not have to run as the same user, but the messagebus port must be
accessible. No firewall blocking, and OVOS must bind on the correct interface (see Configuration).

---

## Install

### From PyPI (standard)

```bash
pip install ovos-ma-player
```

Music Assistant discovers the plugin automatically via the `music_assistant.provider`
entry-point group (key `ovos_player`, declared in `pyproject.toml`). No manual registration is
needed. After installation, restart MA and the provider appears in the UI under
**Settings > Players > Add Provider > OpenVoiceOS (OCP)**.

### Inside a Python virtual environment

If MA runs in a venv (common for standalone installs):

```bash
source /path/to/ma-venv/bin/activate
pip install ovos-ma-player
# then restart MA
```

### Home Assistant add-on

If MA runs as the official Home Assistant add-on, install the plugin through the add-on's
**configuration** page under **Extra pip packages**:

```
ovos-ma-player
```

Save, then restart the add-on. OVOS must be reachable from the HA host on port 8181.

### Docker

If MA runs in Docker, add the package to the container's Python environment. Using the official
MA Docker image, set the `EXTRA_PACKAGES` environment variable or extend the image:

```dockerfile
FROM ghcr.io/music-assistant/server:latest
RUN pip install ovos-ma-player
```

Rebuild and restart the container. If OVOS runs on the Docker host, use `host.docker.internal`
(on Mac/Windows) or the host's LAN IP (on Linux) as the messagebus host in MA config.

---

## Quick Start

Follow these steps from scratch assuming MA is already running.

1. **Verify OVOS is running and OCP is active.**

   On the OVOS host:
   ```bash
   systemctl status ovos-core   # or however you run OVOS
   pip show ovos-skill-ocp      # should print package info, not "not found"
   ```

2. **Verify the messagebus is reachable from the MA host.**

   From the machine running MA (replace `OVOS_HOST` with the actual IP or `localhost`):
   ```bash
   python3 -c "
   from ovos_bus_client import MessageBusClient
   b = MessageBusClient(host='OVOS_HOST', port=8181)
   b.run_in_thread()
   b.connected_event.wait(5)
   print('connected:', b.connected_event.is_set())
   b.close()
   "
   ```
   Expected output: `connected: True`. If you see `False`, see Troubleshooting below.

3. **Install the plugin.**
   ```bash
   pip install ovos-ma-player   # inside MA's Python environment
   ```

4. **Restart Music Assistant.**

5. **Add the provider in the MA UI.**
   - Go to **Settings > Players**.
   - Click **Add Provider**.
   - Select **OpenVoiceOS (OCP)**.
   - Fill in `host` and `port` (leave defaults if OVOS is on the same machine).
   - Click **Save**.

6. **Play something.**
   - In the MA UI, browse to any track and press play.
   - Select **OVOS / OCP** as the target player.
   - Audio should start on the OVOS device within a second or two.

---

## Configuration

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `host` | string | `localhost` | no | Hostname or IP of the machine running OVOS. Must be reachable from MA. |
| `port` | integer | `8181` | no | OVOS messagebus WebSocket port. Change only if you have a non-standard OVOS setup. |

### What MA stores internally

MA stores provider configuration as JSON in its database. The section for this provider looks
like this:

```json
{
  "type": "player",
  "domain": "ovos_player",
  "values": {
    "host": "192.168.1.50",
    "port": 8181
  }
}
```

You do not edit this file directly; use the MA UI. It is shown here so you understand what each
field means and where it ends up.

### What happens if configuration is wrong

- **Wrong host or port:** The provider raises `ProviderUnavailableError` during init (after a
  10-second timeout) and appears as "unavailable" in the MA player list.
- **Port firewalled or OVOS not running:** Same result as wrong host.
- **OVOS running but OCP not installed:** The provider connects successfully (messagebus is up)
  but `ovos.common_play.play` messages are silently ignored by OVOS. No audio plays.

### OVOS bind address

By default, OVOS binds the messagebus only to `localhost`. If MA runs on a different machine,
edit `~/.config/mycroft/mycroft.conf` on the OVOS host:

```json
{
  "websocket": {
    "host": "0.0.0.0",
    "port": 8181
  }
}
```

Restart OVOS after changing this. Exposing 8181 on `0.0.0.0` with no authentication means any
machine on the local network can send arbitrary messages to OVOS. Keep this behind a firewall or
use `hivemind-ma-player` if you need authentication.

---

## Architecture overview

```
+------------------------+          OCP bus messages (WebSocket)
|   Music Assistant      |  ------> ovos.common_play.play
|   (MA server)          |  ------> ovos.common_play.pause
|                        |  ------> ovos.common_play.resume
|  OVOSPlayerProvider    |  ------> ovos.common_play.stop
|  OVOSPlayer            |  ------> ovos.common_play.set_track_position
|                        |  ------> mycroft.volume.set
+------------------------+
        ^  |
        |  | ws://host:8181/core
        |  v
+------------------------+          OCP state events (push)
|   OVOS / OCP           |  ------> ovos.common_play.player.state
|   (on same host or LAN)|  ------> ovos.common_play.media.state
|                        |          (poll response)
|   MessageBusClient     |  <------ ovos.common_play.status
|   (daemon thread)      |  ------> ovos.common_play.status.response
+------------------------+
        |
        v
+------------------------+
|   Audio backend        |
|   (VLC, mpd, etc.)     |
+------------------------+
```

MA lives entirely on one side; OVOS lives on the other. The WebSocket is the only wire between
them. See [docs/architecture.md](docs/architecture.md) for a full class diagram, threading
model, and detailed message reference.

---

## How it works

### Connection

On provider init, `OVOSPlayerProvider.handle_async_init` (`ovos_ma_player/__init__.py:231`)
creates a `MessageBusClient` connecting to `ws://<host>:<port>/core` with SSL disabled. The
client runs its own WebSocket receive loop in a daemon thread (`bus.run_forever()`). MA blocks
for up to 10 seconds waiting for `bus.connected_event`; if the connection is not established the
provider raises `ProviderUnavailableError` and MA marks it as unavailable.

### Player registration

`discover_players` (`ovos_ma_player/__init__.py:283`) registers a single `OVOSPlayer` instance
with player ID `<instance_id>:ovos`. Because `multi_instance` is `false` in `manifest.json`, MA
allows only one instance of this provider per server.

### Command flow (MA to OVOS)

All playback commands run on the asyncio event loop and offload the synchronous bus call to a
thread pool via `asyncio.to_thread` to avoid blocking the loop.

| MA action | OCP message emitted | Payload |
|---|---|---|
| Play (resume) | `ovos.common_play.resume` | none |
| Pause | `ovos.common_play.pause` | none |
| Stop | `ovos.common_play.stop` | none |
| Seek | `ovos.common_play.set_track_position` | `{"position": <float seconds>}` |
| Volume | `mycroft.volume.set` | `{"percent": <0.0-1.0>}` |
| Mute | `mycroft.volume.mute` | none |
| Unmute | `mycroft.volume.unmute` | none |
| Play media | `ovos.common_play.play` | `{"media": <MediaEntry dict>}` |
| Announcement | `ovos.common_play.play` | `{"media": <MediaEntry dict>}` |

For `play_media` and `play_announcement`, MA first resolves the stream URL via
`mass.streams.resolve_stream_url`, then builds an OCP `MediaEntry` and emits
`ovos.common_play.play`.

### State sync (OVOS to MA)

State is kept in sync via two complementary mechanisms:

**Push (event-driven):** The provider subscribes to:
- `ovos.common_play.player.state`: carries a `state` integer (`0`=stopped, `1`=playing,
  `2`=paused). Updates all registered players immediately.
- `ovos.common_play.media.state`: when `state` is `6` (END) or `7` (ERROR), clears
  `current_media` and sets playback state to IDLE.

**Pull (polling fallback):** `OVOSPlayer.needs_poll` returns `True`. MA calls `poll()` every
5 seconds while playing and every 30 seconds while idle/paused. `poll()` sends
`ovos.common_play.status` and waits up to 2 seconds for
`ovos.common_play.status.response`. The response carries `state` and a `media` dict with a
`position` field (elapsed seconds) used to update `_attr_elapsed_time`.

---

## Verifying it works

### MA UI

After adding the provider and pressing play:
- The player tile in MA shows **"OVOS / OCP"** with a green status indicator.
- The progress bar advances as the track plays.
- Pause/resume and volume controls respond within about one second.

If the player tile shows as grey or "unavailable", the connection failed. See Troubleshooting.

### Watching the messagebus

On the OVOS host, run:

```bash
ovos-bus-client monitor
```

When you press play in MA you should see messages like:

```
>> ovos.common_play.play  {"media": {"uri": "http://...", "title": "...", ...}}
<< ovos.common_play.player.state  {"state": 1}
```

The `>>` direction is MA sending to OVOS; `<<` is OVOS replying. If you see the play message but
no state response, OCP is not running or not handling the message.

---

## Troubleshooting

**Provider appears as "unavailable" after adding**

Symptom: The player tile in MA is grey immediately after saving the config.

Cause: MA could not connect to `ws://<host>:<port>/core` within 10 seconds.

Fix:
- Confirm OVOS is running: `systemctl status ovos-core` or equivalent.
- Test the WebSocket from the MA host:
  ```bash
  python3 -c "
  from ovos_bus_client import MessageBusClient
  b = MessageBusClient(host='YOUR_OVOS_HOST', port=8181)
  b.run_in_thread()
  ok = b.connected_event.wait(5)
  print('connected:', ok)
  b.close()
  "
  ```
- Check that port 8181 is not firewalled: `nc -zv OVOS_HOST 8181`
- Check that OVOS binds on `0.0.0.0` if MA is on a different machine (see Configuration).

---

**Playback starts in MA but no audio comes out of OVOS**

Symptom: MA shows the track as "playing" but the OVOS device is silent.

Cause: OCP is not installed or not active in OVOS.

Fix:
- On the OVOS host: `pip show ovos-skill-ocp`: if not found, install it.
- Check OVOS logs: `journalctl -u ovos-core -f` and look for OCP errors.
- Watch the bus (`ovos-bus-client monitor`) and confirm `ovos.common_play.play` arrives and
  OCP responds with a `player.state` event.

---

**State in MA is always IDLE even while OVOS is playing**

Symptom: Progress bar does not move; pausing in MA has no visible effect.

Cause: OCP state events are not reaching MA.

Fix:
- Run `ovos-bus-client monitor` on the OVOS host and trigger playback. Look for
  `ovos.common_play.player.state` events. If they don't appear, OCP is not emitting them: check OCP version and configuration.
- If events appear on the OVOS bus but MA still shows IDLE, the polling fallback is also
  failing. Check network latency and that `ovos.common_play.status` messages receive a response
  within 2 seconds.

---

**Volume commands have no effect**

Symptom: Dragging the volume slider in MA does nothing.

Cause: Some OVOS audio backends do not implement `mycroft.volume.set`.

Fix: Check your OVOS audio backend configuration. The volume message is `mycroft.volume.set`
with payload `{"percent": 0.0-1.0}`. Watch the bus to confirm it arrives, then check whether
the backend handles it.

---

**"ovos-bus-client not installed" error in MA logs**

Symptom: MA shows an error and the provider is unavailable immediately.

Cause: `ovos-bus-client` is not installed in MA's Python environment.

Fix: `pip install ovos-bus-client` inside MA's venv (or add it as an extra package in the HA
add-on config).

---

**Seek has no effect**

Symptom: Dragging the seek bar in MA does not change the playback position.

Cause: The OCP backend in OVOS may not support seeking, or OCP may silently ignore the
`ovos.common_play.set_track_position` message for the current media type.

Fix: Check the OVOS OCP backend documentation. Not all backends support arbitrary seeking.

---

**Provider connects but `multi_instance` blocks adding a second one**

Symptom: MA refuses to add a second instance of this provider.

Cause: `manifest.json` sets `multi_instance: false`. This is intentional: one OVOS instance
per MA server. If you need to control multiple OVOS devices, use `hivemind-ma-player` instead,
which supports multiple simultaneous instances.

---

**MA restarts and the player is gone**

Symptom: After restarting MA the OVOS player no longer appears.

Cause: Normal behaviour if `handle_async_init` fails (OVOS not running at MA startup). MA will
retry when you reload the provider.

Fix: Ensure OVOS starts before MA, then reload or restart MA.

---

**Announcements interrupt music and music does not resume**

Symptom: Playing an announcement via MA TTS stops the current track and it does not resume.

Cause: `play_announcement` sends the same `ovos.common_play.play` message as `play_media`. OCP
treats it as a new track. Resume-after-announcement is not implemented in this provider; it
relies on OCP's own interrupt/resume logic.

Fix: This is a known limitation. OCP's native announcement handling (duck audio, play TTS,
restore) is separate from OCP media playback and would require a different message type. Track
this as a future enhancement.

---

## Developer notes

The provider follows the standard MA plugin pattern:

- Module-level `setup()` and `get_config_entries()` are the MA plugin entry points
  (`ovos_ma_player/__init__.py:48`, `ovos_ma_player/__init__.py:54`).
- `OVOSPlayerProvider` extends `PlayerProvider`. Initialization lives in
  `handle_async_init` (called by MA after the asyncio loop is running).
- `OVOSPlayer` extends `Player`. Each command method is `async` and offloads the
  synchronous bus call via `asyncio.to_thread`.
- `_make_media_entry` (`ovos_ma_player/__init__.py:159`) converts MA's `PlayerMedia` to an OCP
  `MediaEntry`. Imports from `ovos_utils.ocp` are deferred to avoid hard failures when the
  package is not installed at import time.

See [docs/architecture.md](docs/architecture.md) for the full class diagram, OCP message
reference, and threading model, and [docs/plugin-authors.md](docs/plugin-authors.md) for
guidance on forking and extending the plugin.

---

## Related

- [hivemind-ma-player](https://github.com/TigreGotico/hivemind-ma-player): same protocol over
  an encrypted HiveMind tunnel; use this when OVOS is on a remote device.

---

## License

Apache 2.0
