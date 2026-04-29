# Architecture — ovos-ma-player

## Class diagram

```
music_assistant.models.player_provider.PlayerProvider
    └── OVOSPlayerProvider                  (ovos_ma_player/__init__.py:226)
            │  owns bus: MessageBusClient
            │  owns players: list[Player]
            └── registers
                    OVOSPlayer              (ovos_ma_player/__init__.py:83)
                        extends music_assistant.models.player.Player
                        back-ref provider → OVOSPlayerProvider
```

`OVOSPlayerProvider` holds the single `MessageBusClient` instance and exposes it (and
`Message`) as attributes that `OVOSPlayer` uses. `OVOSPlayer` never touches the bus
directly; it always goes through `self.provider.bus`.

---

## Threading model

Music Assistant runs on a single asyncio event loop. `MessageBusClient` from `ovos-bus-client`
is synchronous and runs its own WebSocket receive loop internally.

**Why a daemon thread for the bus**

`handle_async_init` starts `bus.run_forever()` in a `threading.Thread(daemon=True)`. This is
required because `run_forever()` blocks until the connection is closed. The daemon flag ensures
the thread does not prevent Python from exiting when MA shuts down.

**Why `asyncio.to_thread`**

Every bus call (`bus.emit`, `bus.wait_for_response`) is synchronous and may block (network I/O,
response wait). Calling them directly from an `async` method would block the event loop.
`asyncio.to_thread` offloads each call to the default thread-pool executor, keeping the event
loop responsive.

**Connection handshake**

After starting the daemon thread, `handle_async_init` calls `bus.connected_event.wait(timeout=10)`
(which is itself synchronous, run via the implicit thread created by `run_forever`). If the event
is not set within 10 seconds, the provider raises `ProviderUnavailableError`.

**Event callbacks**

`_on_player_state` and `_on_media_state` are registered with `bus.on(...)`. These callbacks are
invoked by the bus receive thread, not the asyncio event loop. They only mutate `_attr_*`
attributes and call `player.update_state()`. `update_state()` in MA is thread-safe (it schedules
a coroutine on the loop via `loop.call_soon_threadsafe`).

---

## OCP message reference

### Messages sent by MA (MA → OVOS)

| Message type | Payload | Triggered by |
|---|---|---|
| `ovos.common_play.resume` | — | `OVOSPlayer.play` |
| `ovos.common_play.pause` | — | `OVOSPlayer.pause` |
| `ovos.common_play.stop` | — | `OVOSPlayer.stop`, `OVOSPlayer.power(False)` |
| `ovos.common_play.set_track_position` | `{"position": float}` (seconds) | `OVOSPlayer.seek` |
| `mycroft.volume.set` | `{"percent": float}` (0.0–1.0) | `OVOSPlayer.volume_set` |
| `mycroft.volume.mute` | — | `OVOSPlayer.volume_mute(True)` |
| `mycroft.volume.unmute` | — | `OVOSPlayer.volume_mute(False)` |
| `ovos.common_play.play` | `{"media": MediaEntry dict}` | `OVOSPlayer.play_media`, `OVOSPlayer.play_announcement` |
| `ovos.common_play.status` | — | `OVOSPlayer.poll` |

### Messages received by MA (OVOS → MA)

| Message type | Payload | Handler |
|---|---|---|
| `ovos.common_play.player.state` | `{"state": int}` | `OVOSPlayerProvider._on_player_state` |
| `ovos.common_play.media.state` | `{"state": int}` | `OVOSPlayerProvider._on_media_state` |
| `ovos.common_play.status.response` | `{"state": int, "media": {"position": float, ...}}` | `OVOSPlayer.poll` (via `wait_for_response`) |

---

## State machine

### MA PlaybackState ↔ OCP PlayerState

OCP exposes a `PlayerState` IntEnum (from `ovos_utils.ocp`):

| OCP value | OCP name | MA PlaybackState |
|---|---|---|
| `0` | STOPPED | `PlaybackState.IDLE` |
| `1` | PLAYING | `PlaybackState.PLAYING` |
| `2` | PAUSED | `PlaybackState.PAUSED` |

### OCP MediaState → MA PlaybackState

`ovos.common_play.media.state` carries a `MediaState` int. Values `6` (END) and `7` (ERROR)
both map to `PlaybackState.IDLE` and clear `current_media`.

`_on_media_state` — `ovos_ma_player/__init__.py:272`

### Optimistic state updates

Command methods (`play`, `pause`, `stop`, `volume_set`, `volume_mute`) update `_attr_*` and
call `update_state()` immediately after emitting the bus message, without waiting for OVOS to
confirm. This gives MA a responsive UI. The push events and poll cycle will correct any
discrepancy within 5 seconds.

---

## MediaEntry fields

`OVOSPlayer._make_media_entry` — `ovos_ma_player/__init__.py:159`

| Field | Source | Notes |
|---|---|---|
| `uri` | MA stream URL (resolved by `mass.streams.resolve_stream_url`) | OCP fetches audio from this URL |
| `title` | `PlayerMedia.title` | Falls back to URL string |
| `artist` | `PlayerMedia.artist_name` | Empty string if absent |
| `length` | `PlayerMedia.duration` (cast to int seconds) | `0` if absent |
| `match_confidence` | hardcoded `100` | Tells OCP this is a direct play, not a fuzzy match |
| `skill_id` | `"music_assistant"` | OCP uses this for source attribution |
| `status` | `TrackState.QUEUED_AUDIO` | Initial state before playback starts |
| `media_type` | `MediaType.MUSIC` | All MA audio is treated as music |
| `playback` | `PlaybackType.AUDIO` | Selects the audio-only pipeline in OCP |
| `image` | `PlayerMedia.image_url` | Album/track art, passed through to OVOS GUI |

`ovos_utils.ocp` imports (`MediaEntry`, `MediaType`, `PlaybackType`, `TrackState`) are deferred
inside the method body to avoid a hard import failure when `ovos-utils` is absent at module
load time.
