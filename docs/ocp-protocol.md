# OCP Protocol Reference

This document is the authoritative reference for the OCP (OpenVoiceOS Common Play) bus messages
used by this plugin. It covers every message type, payload schema, example payloads, enum values,
and known gotchas.

The same protocol applies to `hivemind-ma-player`; the transport differs but the messages are
identical. See [hivemind-ma-player/docs/ocp-protocol.md](../../hivemind-ma-player/docs/ocp-protocol.md)
for the HiveMind-specific differences.

---

## Message format

Every OVOS bus message is a JSON object with three fields:

```json
{
  "type": "ovos.common_play.play",
  "data": { ... },
  "context": { ... }
}
```

- `type` — the message type string; the routing key.
- `data` — message-specific payload dict. May be empty (`{}`).
- `context` — routing metadata (skill ID, session, etc.). This plugin never sets context fields.

In code, messages are created as `Message(msg_type, data_dict)` from `ovos_bus_client`.

---

## Messages sent by this plugin (MA to OVOS)

### ovos.common_play.play

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.play_media` (`:252`), `OVOSPlayer.play_announcement` (`:264`)

**Purpose:** Instruct OCP to play a specific media item immediately.

**How the payload is built:** `_make_ocp_media_entry` (`:82`) creates a `MediaEntry` using
`ovos_pydantic_models.skills.ocp.MediaEntry` and calls `model_dump()`. `_make_play_payload`
(`:102`) wraps it in `OvosCommonPlayPlayData`:

```python
OvosCommonPlayPlayData(
    media=entry_dict,
    disambiguation=[],
    playlist=[entry_dict],
).model_dump()
```

**Payload schema:**

```json
{
  "media": {
    "uri": "http://ma-server:8095/stream/...",
    "title": "Track Title",
    "artist": "Artist Name",
    "length": 213000,
    "match_confidence": 1.0,
    "skill_id": "music_assistant",
    "media_type": "music",
    "playback": "audio",
    "image": "https://example.com/cover.jpg"
  },
  "disambiguation": [],
  "playlist": [{ ... same as media ... }]
}
```

Note: `media_type` and `playback` are serialized as strings (pydantic enum serialization); the
exact string values depend on `ovos_pydantic_models` version. `length` is in **milliseconds**
(MA's `duration` in seconds multiplied by 1000, `ovos_ma_player/__init__.py:92`).
`match_confidence` is a float `1.0` (not integer 100).

**Gotchas:**
- `uri` must be reachable from the OVOS host. If MA is on a different machine, ensure the
  stream URL uses an externally reachable address.
- `length` is in milliseconds. If you send seconds by mistake, OCP will show wrong seek range
  and may stop playback prematurely (1000x too early).
- `playlist` containing the same entry as `media` is intentional — OCP uses the playlist for
  queue display.

All line numbers refer to `ovos_ma_player/__init__.py`.

---

### ovos.common_play.resume

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.play` (`:210`)

**Purpose:** Resume playback if paused.

**Payload:** `{}` (empty)

**Gotcha:** If OCP is stopped (not just paused), this message may have no effect. The plugin
assumes OCP is in PAUSED state when MA calls `play()`. If OCP is fully stopped, use
`ovos.common_play.play` with a new `MediaEntry` instead.

---

### ovos.common_play.pause

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.pause` (`:214`)

**Purpose:** Pause current playback without clearing the queue.

**Payload:** `{}` (empty)

---

### ovos.common_play.stop

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.stop` (`:219`), `OVOSPlayer.power(False)` (`:247`)

**Purpose:** Stop playback and clear the OCP queue.

**Payload:** `{}` (empty)

---

### ovos.common_play.set_track_position

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.seek` (`:225`)

**Purpose:** Seek to a specific position in the current track.

**Payload:**

```json
{"position": 90500}
```

- `position`: integer, position in **milliseconds** from the start of the track.

MA passes position in seconds; the plugin multiplies by 1000:

```python
# ovos_ma_player/__init__.py:229
{"position": int(position * 1000)}
```

**Gotcha:** Not all OCP audio backends support seeking. No error is returned on failure. The
next `poll()` call reads back the actual position.

---

### mycroft.volume.set

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.volume_set` (`:232`)

**Purpose:** Set the playback volume.

**Payload:**

```json
{"percent": 0.75}
```

- `percent`: float from `0.0` (silent) to `1.0` (maximum). MA's 0-100 integer is divided by
  100 (`ovos_ma_player/__init__.py:234`: `volume_level / 100`).

**Gotcha:** This is a Mycroft-era message name. Some OVOS audio backends handle it; some do
not. If volume control has no effect, check the backend. Requires `ovos-phal-plugin-alsa` or
equivalent for hardware volume control.

---

### mycroft.volume.mute / mycroft.volume.unmute

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.volume_mute` (`:239`)

**Purpose:** Mute or unmute the OVOS audio output.

**Payload:** `{}` (empty)

---

### ovos.common_play.status

**Direction:** MA -> OVOS

**Triggered by:** `OVOSPlayer.poll` (`:275`)

**Purpose:** Request the current OCP playback state. OCP responds with
`ovos.common_play.status.response`.

**Payload:** `{}` (empty)

The plugin uses `wait_for_response` with a 2-second timeout (`:280`). If OCP does not respond
within 2 seconds, the poll silently returns without updating state.

---

## Messages received by this plugin (OVOS to MA)

### ovos.common_play.player.state

**Direction:** OVOS -> MA

**Handler:** `OVOSPlayerProvider._on_player_state` (`:332`) via `_parse_player_state` (`:112`)

**Purpose:** Notify all listeners of a player state change.

**Payload:**

```json
{"state": "playing"}
```

The `state` field is a `PlayerState` value from `ovos_pydantic_models.skills.ocp`. The payload
is validated using `OvosCommonPlayPlayerStateData`. If validation fails, the handler logs a
warning and returns without updating state.

**When fired:** On every OCP player state transition.

---

### ovos.common_play.media.state

**Direction:** OVOS -> MA

**Handler:** `OVOSPlayerProvider._on_media_state` (`:342`) via `_parse_media_state_end` (`:129`)

**Purpose:** Notify listeners of media pipeline state changes.

**Payload:**

```json
{"state": "end_of_media"}
```

Validated using `OvosCommonPlayMediaStateData` from `ovos_pydantic_models.audio.ocp`. The
handler only acts when `state` is `OcpMediaState.END_OF_MEDIA` or
`OcpMediaState.INVALID_MEDIA` — both reset the player to IDLE and clear `current_media`.

**Why not `ovos.common_play.track.state`?** Per-track pipeline events are more granular than
needed. `media.state` provides the reliable "pipeline is done" signal.

---

### ovos.common_play.status.response

**Direction:** OVOS -> MA

**Received by:** `OVOSPlayer.poll` (`:275`) via `_parse_status_response` (`:142`)

**Purpose:** Response to `ovos.common_play.status`. Carries current state and media position.

**Payload example:**

```json
{
  "state": "playing",
  "media": {
    "uri": "http://...",
    "title": "Track Title",
    "position": 42300
  }
}
```

`_parse_status_response` validates this with `OvosCommonPlayStatusResponseData` and returns
`(PlaybackState | None, int | None)`. The integer is elapsed time in milliseconds. The plugin
converts to seconds: `elapsed_ms // 1000` (`:290`). `media` may be `None` if nothing is
playing.

---

## Payload validation and error handling

All incoming payloads are validated by pydantic models from `ovos_pydantic_models` (imported
lazily inside each helper function). If validation fails:

- `_parse_player_state` returns `None` — the handler skips the update.
- `_parse_media_state_end` returns `False` — the handler takes no action.
- `_parse_status_response` returns `(None, None)` — no state or position update.

A `WARNING` log is emitted in each case with the validation exception. This means a malformed
OCP message causes a log warning rather than an exception or silent data corruption.

---

## Enum values and model locations

The plugin uses pydantic models from `ovos_pydantic_models` for validation. The raw string
values on the bus depend on that library's enum serialization.

### PlayerState (ovos_pydantic_models.skills.ocp.PlayerState)

| Name | MA PlaybackState |
|---|---|
| `PLAYING` | `PlaybackState.PLAYING` |
| `PAUSED` | `PlaybackState.PAUSED` |
| `STOPPED` / `LOADING` / `BUFFERING` / other | `PlaybackState.IDLE` |

### OcpMediaState (ovos_pydantic_models.audio.ocp.OcpMediaState)

Only two values cause action in this plugin:

| Name | Plugin action |
|---|---|
| `END_OF_MEDIA` | -> MA IDLE, clear current_media |
| `INVALID_MEDIA` | -> MA IDLE, clear current_media |
| all others | ignored |

### MediaType (ovos_pydantic_models.skills.ocp.MediaType)

The plugin always uses `MediaType.MUSIC`.

### PlaybackType (ovos_pydantic_models.skills.ocp.PlaybackType)

The plugin always uses `PlaybackType.AUDIO`.

---

## MediaEntry serialization summary

`_make_ocp_media_entry(url, media)` — `ovos_ma_player/__init__.py:82`

| Field | Value | Notes |
|---|---|---|
| `uri` | MA stream URL | Must be reachable from OVOS host |
| `title` | `PlayerMedia.title` or URL | Cosmetic |
| `artist` | `PlayerMedia.artist_name` or `""` | Cosmetic |
| `length` | `int(duration_s * 1000)` | Milliseconds; `0` if duration unknown |
| `match_confidence` | `1.0` | Float, normalised 0.0-1.0 range |
| `skill_id` | `"music_assistant"` | Source attribution in OCP logs/GUI |
| `media_type` | `MediaType.MUSIC` | Selects OCP content category |
| `playback` | `PlaybackType.AUDIO` | Selects audio-only backend |
| `image` | `PlayerMedia.image_url` or `""` | Album art for OVOS GUI |

---

## Protocol gotchas summary

1. **No acknowledgement on emit.** OCP does not ACK `ovos.common_play.play` or other commands.
   The plugin uses optimistic state updates and relies on events/polling to detect failures.

2. **resume vs play.** `ovos.common_play.resume` only works if OCP is in PAUSED state. If OCP
   is STOPPED, send `ovos.common_play.play` with a new `MediaEntry`.

3. **Volume units.** MA uses 0-100 integer scale; OCP uses 0.0-1.0 float. Conversion:
   `percent = volume_level / 100`.

4. **Seek and position are in milliseconds.** Both `set_track_position` payload and
   `status.response` `media.position` use milliseconds. The plugin converts position to seconds
   for `_attr_elapsed_time`: `elapsed_ms // 1000`.

5. **End-of-track detection.** End-of-track is detected via `media.state` (END_OF_MEDIA or
   INVALID_MEDIA), not `track.state`. If `media.state` events are not emitted, the player stays
   in PLAYING state until the next poll (up to 5 seconds).

6. **Multiple OCP sources.** If another skill sends OCP messages to the same OVOS instance,
   their state events will also arrive here. There is no per-source filtering.

7. **pydantic models.** The plugin depends on `ovos_pydantic_models` for payload validation.
   This package is a transitive dependency (via `ovos-bus-client` or related packages) but is
   not declared as a direct dependency. If it is absent, the lazy imports inside the helper
   functions will fail at runtime with an `ImportError`.
