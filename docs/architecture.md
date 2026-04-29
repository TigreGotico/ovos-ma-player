# Architecture — ovos-ma-player

## Class diagram

```
music_assistant.models.player_provider.PlayerProvider
    └── OVOSPlayerProvider                  (ovos_ma_player/__init__.py:301)
            │  owns bus: MessageBusClient
            │  owns players: list[Player]
            │  attr: Message (class)
            └── registers
                    OVOSPlayer              (ovos_ma_player/__init__.py:178)
                        extends music_assistant.models.player.Player
                        back-ref provider -> OVOSPlayerProvider

Module-level helpers (shared between provider and player):
    _make_ocp_media_entry(url, media) -> dict   :82
    _make_play_payload(entry_dict) -> dict       :102
    _parse_player_state(raw) -> PlaybackState   :112
    _parse_media_state_end(raw) -> bool          :129
    _parse_status_response(raw) -> tuple         :142
```

`OVOSPlayerProvider` holds the single `MessageBusClient` instance and exposes it (and the
`Message` class) as instance attributes. `OVOSPlayer` accesses the bus only through
`self.provider.bus` and `self.provider.Message`. This means `ovos-bus-client` can fail to
import without causing an `ImportError` at module load — the failure is caught in
`handle_async_init` and surfaced as `ProviderUnavailableError`.

The message construction, payload validation, and state parsing are all in module-level helper
functions rather than class methods. This makes them independently testable and keeps the player
class focused on state management.

---

## What is a Music Assistant PlayerProvider?

MA has three categories of provider:

- **Music providers** — supply library content (albums, tracks, artists). Examples: Spotify,
  YouTube Music, local files.
- **Player providers** — represent playback devices and translate MA playback commands to
  device-specific protocols. This package is a player provider.
- **Metadata providers** — enrich content with extra information (lyrics, artist bios).

A player provider must implement:

- `handle_async_init()` — called once after the asyncio loop is running; set up connections here.
- `discover_players()` — register `Player` instances with `mass.players.register()`.
- `unload()` — clean up connections on shutdown.

The module must also export:

- `setup(mass, manifest, config) -> ProviderInstanceType` — construct and return the provider.
- `get_config_entries(mass, instance_id, action, values) -> tuple[ConfigEntry, ...]` — describe
  the config form shown in the MA UI.
- `SUPPORTED_FEATURES: set[ProviderFeature]` — provider-level capability flags (empty for player
  providers; see below).

---

## What is OCP?

OCP (OpenVoiceOS Common Play) is OVOS's audio playback subsystem. It operates as a skill on the
OVOS messagebus and owns the complete audio lifecycle:

1. A skill or external client posts `ovos.common_play.play` with a payload containing a
   `MediaEntry` dict and disambiguation/playlist lists.
2. OCP selects an appropriate audio backend (VLC, mpd, GStreamer, etc.) based on the
   `playback` field in the entry.
3. The backend fetches and plays the `uri`.
4. OCP emits state events (`ovos.common_play.player.state`, `ovos.common_play.media.state`) as
   playback progresses.

From OCP's perspective, this plugin is indistinguishable from a regular OCP skill. No special
OCP configuration is required.

---

## Threading model

Music Assistant runs on a single asyncio event loop. `MessageBusClient` from `ovos-bus-client`
is synchronous and runs its own WebSocket receive loop internally.

### Why a daemon thread for the bus

`handle_async_init` starts `bus.run_forever()` in a `threading.Thread(daemon=True)`
(`ovos_ma_player/__init__.py:319`). `run_forever()` blocks indefinitely until the connection
closes. The daemon flag ensures the thread does not prevent Python from exiting when MA shuts
down.

### Why `asyncio.to_thread`

Every bus call (`bus.emit`, `bus.wait_for_response`) is synchronous and may block for a network
round-trip. Calling them directly from an `async` method would block the asyncio event loop,
starving all other coroutines. `asyncio.to_thread` offloads each call to the default thread-pool
executor, keeping the event loop responsive.

Example from `OVOSPlayer.play` (`ovos_ma_player/__init__.py:209`):

```python
async def play(self) -> None:
    await asyncio.to_thread(self._emit, "ovos.common_play.resume")
    self._attr_playback_state = PlaybackState.PLAYING
    self.update_state()
```

`OVOSPlayer._emit` (`ovos_ma_player/__init__.py:206`) is a synchronous helper:

```python
def _emit(self, msg_type: str, data: dict | None = None) -> None:
    self.provider.bus.emit(self.provider.Message(msg_type, data or {}))
```

### Connection handshake

After starting the daemon thread, `handle_async_init` calls
`bus.connected_event.wait(timeout=10)` (`ovos_ma_player/__init__.py:321`). This is a
`threading.Event` set by the bus client's receive loop when the WebSocket handshake completes.
If it is not set within 10 seconds, the provider raises `ProviderUnavailableError`.

### Event callbacks

`_on_player_state` and `_on_media_state` are registered with `bus.on(...)`. These callbacks are
invoked by the bus receive thread, not the asyncio event loop. They only mutate `_attr_*`
attributes and call `player.update_state()`.

`update_state()` in MA is thread-safe: it schedules the state publication coroutine on the event
loop via `loop.call_soon_threadsafe`. Never `await` inside a bus event handler.

### Shutdown

`unload()` (`ovos_ma_player/__init__.py:355`) calls `bus.close()`, which signals the bus client
to stop and terminates the receive loop.

---

## Optimistic state updates

Command methods (`play`, `pause`, `stop`, `volume_set`, `volume_mute`) update `_attr_*` and
call `update_state()` immediately after emitting the bus message, without waiting for OVOS to
acknowledge. This gives MA a responsive UI. Push events and polling will correct any discrepancy
within 5 seconds.

If a command fails silently, MA will briefly display incorrect state. In practice this is rare
and the recovery is fast.

---

## Push vs pull state sync

### Push (event-driven)

Registered in `handle_async_init` (`ovos_ma_player/__init__.py:329-330`):

```python
self.bus.on("ovos.common_play.player.state", self._on_player_state)
self.bus.on("ovos.common_play.media.state", self._on_media_state)
```

State events fire whenever OCP's internal state changes. They are the primary sync mechanism.

### Pull (polling fallback)

`OVOSPlayer.needs_poll` returns `True` (`ovos_ma_player/__init__.py:199`). MA calls `poll()`
every 5 seconds while `PLAYING`, every 30 seconds otherwise (`ovos_ma_player/__init__.py:203`).

`poll()` (`ovos_ma_player/__init__.py:275`) sends `ovos.common_play.status` and waits up to
2 seconds for `ovos.common_play.status.response`. The response is validated by
`_parse_status_response` (`ovos_ma_player/__init__.py:142`), which returns a
`(PlaybackState | None, int | None)` tuple. The integer is elapsed time in milliseconds;
the plugin converts it to seconds with `elapsed_ms // 1000` before storing in
`_attr_elapsed_time` (`ovos_ma_player/__init__.py:290`).

---

## OCP message reference

### Messages sent by MA (MA to OVOS)

| Message type | Payload | Triggered by | Source line |
|---|---|---|---|
| `ovos.common_play.resume` | `{}` | `OVOSPlayer.play` | `:210` |
| `ovos.common_play.pause` | `{}` | `OVOSPlayer.pause` | `:215` |
| `ovos.common_play.stop` | `{}` | `OVOSPlayer.stop`, `OVOSPlayer.power(False)` | `:220` |
| `ovos.common_play.set_track_position` | `{"position": int}` (milliseconds) | `OVOSPlayer.seek` | `:228` |
| `mycroft.volume.set` | `{"percent": float}` (0.0-1.0) | `OVOSPlayer.volume_set` | `:234` |
| `mycroft.volume.mute` | `{}` | `OVOSPlayer.volume_mute(True)` | `:241` |
| `mycroft.volume.unmute` | `{}` | `OVOSPlayer.volume_mute(False)` | `:241` |
| `ovos.common_play.play` | see payload below | `OVOSPlayer.play_media`, `OVOSPlayer.play_announcement` | `:257`, `:270` |
| `ovos.common_play.status` | `{}` | `OVOSPlayer.poll` | `:278` |

All line numbers refer to `ovos_ma_player/__init__.py`.

**Note on seek position units:** OCP `set_track_position` expects **milliseconds**. MA passes
position in seconds; the plugin multiplies by 1000 (`ovos_ma_player/__init__.py:229`).

### ovos.common_play.play payload

The payload is built by `_make_play_payload(entry_dict)` (`ovos_ma_player/__init__.py:102`),
which uses `OvosCommonPlayPlayData` from `ovos_pydantic_models.skills.ocp`:

```json
{
  "media": { ... },
  "disambiguation": [],
  "playlist": [{ ... }]
}
```

`media` and each element of `playlist` are `MediaEntry` dicts (see MediaEntry section below).
`disambiguation` is always an empty list in this plugin — OCP uses it for displaying alternative
results when a user asks to play something by voice.

### Messages received by MA (OVOS to MA)

| Message type | Payload | Handler | Source line |
|---|---|---|---|
| `ovos.common_play.player.state` | `{"state": <PlayerState>}` | `OVOSPlayerProvider._on_player_state` | `:332` |
| `ovos.common_play.media.state` | `{"state": <OcpMediaState>}` | `OVOSPlayerProvider._on_media_state` | `:342` |
| `ovos.common_play.status.response` | `{"state": <PlayerState>, "media": {...}}` | `OVOSPlayer.poll` via `wait_for_response` | `:278` |

For full payload schemas and enum values, see [ocp-protocol.md](ocp-protocol.md).

---

## State machine

### PlayerState

OCP uses a `PlayerState` enum from `ovos_pydantic_models.skills.ocp`. The plugin accesses it
via `_parse_player_state` (`ovos_ma_player/__init__.py:112`), which validates the payload using
`OvosCommonPlayPlayerStateData` and returns an MA `PlaybackState`.

| PlayerState value | MA PlaybackState |
|---|---|
| `PLAYING` | `PlaybackState.PLAYING` |
| `PAUSED` | `PlaybackState.PAUSED` |
| `STOPPED` / `LOADING` / `BUFFERING` / anything else | `PlaybackState.IDLE` |

If the payload fails pydantic validation, `_parse_player_state` returns `None` and the handler
skips the update (rather than crashing).

### End-of-track detection via MediaState

`_parse_media_state_end` (`ovos_ma_player/__init__.py:129`) validates the
`ovos.common_play.media.state` payload using `OvosCommonPlayMediaStateData` and returns `True`
only for `OcpMediaState.END_OF_MEDIA` and `OcpMediaState.INVALID_MEDIA`. All other states are
ignored.

When `_parse_media_state_end` returns `True`, the handler sets the player to IDLE and clears
`current_media` (`ovos_ma_player/__init__.py:342-348`).

Note: `ovos.common_play.track.state` is not subscribed. Per-track pipeline events are more
granular than what MA needs.

---

## MediaEntry fields

`_make_ocp_media_entry(url, media)` — `ovos_ma_player/__init__.py:82`

This module-level function builds an `ovos_pydantic_models.skills.ocp.MediaEntry` and returns
its `model_dump()` dict. It is called via `asyncio.to_thread` because the pydantic
serialization is synchronous.

| Field | Type | Source | What happens if wrong or missing |
|---|---|---|---|
| `uri` | string (URL) | MA stream URL from `mass.streams.resolve_stream_url` | OCP cannot fetch audio; playback fails silently or logs an error |
| `title` | string | `PlayerMedia.title`, falls back to URL | Displayed in OVOS GUI; purely cosmetic |
| `artist` | string | `PlayerMedia.artist_name`, falls back to `""` | Displayed in OVOS GUI; purely cosmetic |
| `length` | int (milliseconds) | `PlayerMedia.duration * 1000` (MA gives seconds, OCP expects ms) | `0` if absent; affects seek range in OCP; `0` disables seeking in some backends |
| `match_confidence` | float (0.0-1.0) | hardcoded `1.0` | Tells OCP this is a direct play, not a fuzzy match. Must be high (1.0) to ensure OCP plays it immediately. |
| `skill_id` | string | hardcoded `"music_assistant"` | OCP attributes the track to this source; used in logs and GUI |
| `media_type` | `MediaType` | `MediaType.MUSIC` | Selects OCP content category; affects backend selection in some setups |
| `playback` | `PlaybackType` | `PlaybackType.AUDIO` | Selects audio-only pipeline |
| `image` | string (URL) | `PlayerMedia.image_url`, falls back to `""` | Album art shown in OVOS GUI; purely cosmetic |

**Note on `length` units:** MA's `PlayerMedia.duration` is in seconds; OCP's `MediaEntry.length`
is in milliseconds. The plugin converts with `int(duration_s * 1000)` (`ovos_ma_player/__init__.py:92`).

**Note on `match_confidence` type:** The field is a float `1.0`, not an integer `100`. The
`ovos_pydantic_models.MediaEntry` schema uses a normalised float range.

All imports from `ovos_pydantic_models.skills.ocp` are deferred inside `_make_ocp_media_entry`
to avoid hard import failures if `ovos-pydantic-models` is absent at module load time.

---

## ProviderFeature vs PlayerFeature

`SUPPORTED_FEATURES` at module level (`ovos_ma_player/__init__.py:34`) is `set[ProviderFeature]`
and is empty. `ProviderFeature` flags advertise provider-level capabilities such as library
browsing. Player providers do not browse libraries.

`OVOSPlayer._attr_supported_features` (`ovos_ma_player/__init__.py:184`) declares per-player
capabilities:

| Flag | MA UI element | What is called |
|---|---|---|
| `PLAY_MEDIA` | Play button (queue item) | `play_media(media)` |
| `POWER` | Power toggle | `power(powered)` |
| `PAUSE` | Pause/resume toggle | `pause()` / `play()` |
| `VOLUME_SET` | Volume slider | `volume_set(level)` |
| `VOLUME_MUTE` | Mute button | `volume_mute(muted)` |
| `SEEK` | Seek bar | `seek(position)` |
| `PLAY_ANNOUNCEMENT` | MA TTS system | `play_announcement(media, volume)` |
