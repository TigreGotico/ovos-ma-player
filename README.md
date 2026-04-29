# ovos-ma-player

Music Assistant PlayerProvider that drives a **local** OpenVoiceOS (OVOS) instance through the
OCP (OpenVoiceOS Common Play) messagebus protocol.

Music Assistant resolves a stream URL and hands it to OVOS/OCP using standard OCP bus messages.
OVOS handles the actual audio pipeline; state changes are pushed back to MA via `ovos.common_play.player.state` events and backed up by a polling fallback.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Required by both MA and this plugin |
| Music Assistant | The server that this plugin extends |
| OVOS with OCP | Must be running on the same host (or reachable LAN IP). OCP is included in standard OVOS installations. |
| OVOS messagebus open | The messagebus WebSocket (`ws://host:8181/core`) must be reachable from MA with no authentication. |

OVOS and Music Assistant do not have to run as the same user, but the messagebus port must be
accessible (no firewall blocking, correct bind address in OVOS config).

---

## Install

```bash
pip install ovos-ma-player
```

Music Assistant discovers the plugin automatically via the `music_assistant.provider` entry-point
group (key `ovos_player`, declared in `pyproject.toml`). No manual registration is needed; after
installation, restart MA and the provider will appear in the UI under **Players > Add Provider**.

---

## Configuration

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `host` | string | `localhost` | no | Hostname or IP of the machine running OVOS. Must be reachable from MA. |
| `port` | integer | `8181` | no | OVOS messagebus WebSocket port. Change only if you have a non-standard OVOS setup. |

**Typical setup (OVOS and MA on the same machine):** leave both fields at their defaults.

**OVOS on a separate host:** set `host` to the IP or hostname of the OVOS machine. Ensure
port 8181 is not blocked by a firewall and that OVOS is configured to bind on `0.0.0.0`
(edit `~/.config/mycroft/mycroft.conf`, key `websocket.host`).

---

## How it works

### Connection

On provider init, `OVOSPlayerProvider.handle_async_init` creates a `MessageBusClient` connecting
to `ws://<host>:<port>/core` with SSL disabled. The client runs its own receive loop in a daemon
thread (`bus.run_forever()`). MA blocks for up to 10 seconds waiting for
`bus.connected_event`; if the connection is not established the provider raises
`ProviderUnavailableError` and MA marks it as unavailable.

### Player registration

`discover_players` registers a single `OVOSPlayer` instance with player ID
`<instance_id>:ovos`. Because `multi_instance` is `false` in the manifest, MA will only
allow one instance of this provider per server.

### Command flow (MA → OVOS)

All playback commands run on the asyncio event loop and offload the synchronous bus call to a
thread pool via `asyncio.to_thread` to avoid blocking the loop.

| MA action | OCP message emitted | Payload |
|---|---|---|
| Play (resume) | `ovos.common_play.resume` | — |
| Pause | `ovos.common_play.pause` | — |
| Stop | `ovos.common_play.stop` | — |
| Seek | `ovos.common_play.set_track_position` | `{"position": <float seconds>}` |
| Volume | `mycroft.volume.set` | `{"percent": <0.0–1.0>}` |
| Mute | `mycroft.volume.mute` | — |
| Unmute | `mycroft.volume.unmute` | — |
| Play media | `ovos.common_play.play` | `{"media": <MediaEntry dict>}` |
| Announcement | `ovos.common_play.play` | `{"media": <MediaEntry dict>}` |

For `play_media` and `play_announcement`, MA first resolves the stream URL via
`mass.streams.resolve_stream_url`, then builds an OCP `MediaEntry` (see architecture docs) and
emits `ovos.common_play.play`.

### State sync (OVOS → MA)

State is kept in sync via two complementary mechanisms:

**Push (event-driven):** The provider subscribes to:
- `ovos.common_play.player.state` — carries a `state` integer (`0`=stopped, `1`=playing,
  `2`=paused). Updates all registered players immediately.
- `ovos.common_play.media.state` — when `state` is `6` (END) or `7` (ERROR), clears
  `current_media` and sets playback state to IDLE.

**Pull (polling fallback):** `OVOSPlayer.needs_poll` returns `True`. MA calls `poll()` every
5 seconds while playing and every 30 seconds while idle/paused. `poll()` sends
`ovos.common_play.status` and waits up to 2 seconds for
`ovos.common_play.status.response`. The response carries `state` and a `media` dict with a
`position` field (elapsed seconds) used to update `_attr_elapsed_time`.

---

## Troubleshooting

**Provider appears as "unavailable" after adding**
- Confirm OVOS is running: `systemctl status ovos` or equivalent.
- Test the WebSocket manually: `python3 -c "from ovos_bus_client import MessageBusClient; b = MessageBusClient(); b.run_in_thread(); b.connected_event.wait(5); print(b.connected_event.is_set())"`.
- Check that the port is not firewalled and that OVOS binds on the correct interface.

**Playback starts but no audio**
- Ensure OCP is installed and active in OVOS (`pip show ovos-skill-ocp`).
- Check OVOS logs for OCP errors (`journalctl -u ovos-core -f`).

**State in MA is always IDLE even while OVOS is playing**
- Verify OCP emits `ovos.common_play.player.state` events: run `ovos-bus-client monitor` on the
  OVOS host and trigger playback.
- The poll fallback runs every 5 s during playback; if both push and poll fail, check
  network latency between MA and OVOS.

**Volume commands have no effect**
- Some OVOS audio backends do not respect `mycroft.volume.set`. Check your audio backend
  configuration in OVOS.

---

## Developer notes

The provider follows the standard MA plugin pattern:

- Module-level `setup()` and `get_config_entries()` are the MA plugin entry points.
- `OVOSPlayerProvider` extends `PlayerProvider`. Initialization lives in
  `handle_async_init` (called by MA after the asyncio loop is running).
- `OVOSPlayer` extends `Player`. Each command method is `async` and offloads the
  synchronous bus call via `asyncio.to_thread`.
- `_make_media_entry` (on `OVOSPlayer`) converts MA's `PlayerMedia` to an OCP
  `MediaEntry`. Imports from `ovos_utils.ocp` are deferred to avoid hard failures when
  the package is not installed at import time.

See [`docs/architecture.md`](docs/architecture.md) for the full class diagram, OCP message
reference, and threading model, and [`docs/plugin-authors.md`](docs/plugin-authors.md) for
guidance on forking and extending the plugin.

---

## License

Apache 2.0
