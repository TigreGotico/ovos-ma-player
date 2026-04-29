# Plugin Authors Guide — ovos-ma-player

This document is for developers who want to fork, extend, or use this plugin as a template for
a new Music Assistant PlayerProvider. It assumes you have read
[architecture.md](architecture.md) and understand the basic MA/OCP model.

---

## How the MA plugin entrypoint system works

Music Assistant discovers provider plugins via the `music_assistant.provider` setuptools
entry-point group. Each entry point maps a key to a Python module path.

### pyproject.toml declaration

```toml
# ovos_ma_player/pyproject.toml
[project.entry-points."music_assistant.provider"]
ovos_player = "ovos_ma_player"
```

The key (`ovos_player`) becomes the provider's `domain`. The value is a Python module path. MA
imports that module and calls `setup()` and `get_config_entries()` on it.

When MA loads a provider it calls two module-level functions:

1. `get_config_entries(mass, instance_id, action, values)` — returns a tuple of `ConfigEntry`
   objects. MA renders these as a configuration form in the UI. Each `ConfigEntry` has a `key`,
   a `type` (`ConfigEntryType.STRING`, `.INTEGER`, `.BOOLEAN`, `.SECURE_STRING`, etc.), a
   `label`, a `default_value`, and a `required` flag.

2. `setup(mass, manifest, config)` — constructs and returns the provider instance. It receives
   the `MusicAssistant` instance, the parsed `manifest.json`, and the user-submitted config.

MA also reads `manifest.json` co-packaged with the Python module. Important manifest fields:

| Field | Type | Description |
|---|---|---|
| `type` | string | Must be `"player"` for player providers |
| `domain` | string | Must match the entry-point key |
| `name` | string | Display name in MA UI |
| `multi_instance` | boolean | If `true`, multiple instances can be added |
| `requirements` | list | Python packages MA should install |
| `stage` | string | `"stable"`, `"beta"`, or `"experimental"` |

### Complete minimal manifest

```json
{
  "type": "player",
  "domain": "my_player",
  "name": "My Custom Player",
  "description": "Controls My Device via its API.",
  "codeowners": ["@your-github-handle"],
  "stage": "beta",
  "requirements": ["my-device-sdk"],
  "multi_instance": false
}
```

### multi_instance

`multi_instance: false` means MA refuses to add a second instance of this provider. This is
correct when there is exactly one target device (one OVOS instance on the same machine).

`multi_instance: true` allows arbitrary instances. Use this when each instance represents a
different physical device (as in `hivemind-ma-player`). When `multi_instance` is true, use the
`instance_id` (available on the provider as `self.instance_id`) to namespace player IDs and
avoid collisions.

---

## Creating a new MA PlayerProvider from scratch

The minimum viable player provider requires:

1. A Python module with `setup()`, `get_config_entries()`, and `SUPPORTED_FEATURES`.
2. A class extending `PlayerProvider`.
3. A class extending `Player`.
4. A `manifest.json`.
5. A `pyproject.toml` with the entry-point.

### Skeleton

```python
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from music_assistant_models.config_entries import ConfigEntry, ConfigValueType
from music_assistant_models.enums import ConfigEntryType, PlaybackState, PlayerFeature, ProviderFeature
from music_assistant_models.player import PlayerMedia
from music_assistant.models.player import Player
from music_assistant.models.player_provider import PlayerProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES: set[ProviderFeature] = set()

async def setup(mass, manifest, config) -> ProviderInstanceType:
    return MyPlayerProvider(mass, manifest, config, SUPPORTED_FEATURES)

async def get_config_entries(mass, instance_id=None, action=None, values=None):
    return (
        ConfigEntry(key="host", type=ConfigEntryType.STRING,
                    label="Device host", required=True),
    )

class MyPlayer(Player):
    def __init__(self, provider, player_id):
        super().__init__(provider, player_id)
        self._attr_name = "My Player"
        self._attr_supported_features = {PlayerFeature.PLAY_MEDIA, PlayerFeature.PAUSE}
        self._attr_playback_state = PlaybackState.IDLE
        self._attr_powered = True

    async def play_media(self, media: PlayerMedia) -> None:
        url = await self.provider.mass.streams.resolve_stream_url(self.player_id, media)
        # send url to device
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def pause(self) -> None:
        # send pause to device
        self._attr_playback_state = PlaybackState.PAUSED
        self.update_state()

class MyPlayerProvider(PlayerProvider):
    async def handle_async_init(self) -> None:
        host = self.config.get_value("host")
        # connect to device

    async def discover_players(self) -> None:
        player = MyPlayer(self, f"{self.instance_id}:main")
        await self.mass.players.register(player)

    async def unload(self) -> None:
        pass  # disconnect
```

---

## Player base class methods you can override

`Player` (from `music_assistant.models.player`) defines the following overridable async methods.
Only implement the ones your device supports, and declare the corresponding `PlayerFeature` flag.

| Method | PlayerFeature flag | Description |
|---|---|---|
| `play_media(media: PlayerMedia)` | `PLAY_MEDIA` | Start playing the given media item |
| `play_announcement(announcement, volume_level)` | `PLAY_ANNOUNCEMENT` | Play a TTS/alert audio clip |
| `pause()` | `PAUSE` | Pause playback |
| `play()` | `PAUSE` | Resume from pause (same flag covers both) |
| `stop()` | — | Stop playback and clear queue |
| `seek(position: int)` | `SEEK` | Seek to position in seconds |
| `volume_set(volume_level: int)` | `VOLUME_SET` | Set volume (0-100) |
| `volume_mute(muted: bool)` | `VOLUME_MUTE` | Mute or unmute |
| `power(powered: bool)` | `POWER` | Power on or off |
| `next_track()` | `NEXT_PREVIOUS_TRACK` | Skip to next track |
| `previous_track()` | `NEXT_PREVIOUS_TRACK` | Go to previous track |
| `poll()` | — | Called periodically if `needs_poll` returns `True` |
| `on_unload()` | — | Called when the player is being removed |

### needs_poll and poll_interval

If your device does not push state events, implement `poll()` and set `needs_poll = True`.
MA will call `poll()` at the interval returned by `poll_interval` (in seconds):

```python
@property
def needs_poll(self) -> bool:
    return True

@property
def poll_interval(self) -> int:
    # Poll more frequently while playing to keep progress bar accurate
    return 5 if self._attr_playback_state == PlaybackState.PLAYING else 30
```

`ovos_ma_player/__init__.py:199-204`

---

## PlayerFeature flags

`PlayerFeature` is an `IntFlag` from `music_assistant_models.enums`. Flags you declare in
`_attr_supported_features` determine which controls MA renders in the UI.

| Flag | UI element | Method called |
|---|---|---|
| `PLAY_MEDIA` | Play button (for a queue item) | `play_media(media)` |
| `PAUSE` | Pause/resume toggle | `pause()` / `play()` |
| `SEEK` | Progress bar (draggable) | `seek(position)` |
| `VOLUME_SET` | Volume slider | `volume_set(level)` |
| `VOLUME_MUTE` | Mute button | `volume_mute(muted)` |
| `POWER` | Power on/off toggle | `power(powered)` |
| `PLAY_ANNOUNCEMENT` | Used by MA TTS/alert system | `play_announcement(media, volume)` |
| `NEXT_PREVIOUS_TRACK` | Next/prev track buttons | `next_track()` / `previous_track()` |
| `SHUFFLE` | Shuffle toggle | `set_shuffle(enabled)` |
| `REPEAT` | Repeat mode button | `set_repeat(mode)` |
| `ENQUEUE` | Queue management | (internal MA handling) |

Only declare flags you have implemented. MA will call the method when the user activates the
control; if the method is not implemented, MA raises a `NotImplementedError` at runtime.

---

## Adding NEXT/PREV track support

OCP supports next/previous via these messages:

```python
# Add to _attr_supported_features in __init__:
PlayerFeature.NEXT_PREVIOUS_TRACK,

# Implement the methods:
async def next_track(self) -> None:
    await asyncio.to_thread(self.provider.bus.emit,
                            self.provider.Message("ovos.common_play.next"))

async def previous_track(self) -> None:
    await asyncio.to_thread(self.provider.bus.emit,
                            self.provider.Message("ovos.common_play.prev"))
```

Verify that your OCP version handles `ovos.common_play.next` and `ovos.common_play.prev`
before advertising this feature. Watch the bus with `ovos-bus-client monitor` and check
whether OCP advances the track.

---

## Adding SHUFFLE/REPEAT support

OCP does not have a standard shuffle/repeat protocol as of the current OCP version. If you add
these features, you will need to manage the queue order on the MA side or use OVOS GUI messages
specific to your setup.

To declare the flags without crashing:

```python
PlayerFeature.SHUFFLE,
PlayerFeature.REPEAT,

async def set_shuffle(self, enabled: bool) -> None:
    # Implement or raise NotImplementedError to suppress in MA UI
    pass

async def set_repeat(self, mode) -> None:
    pass
```

---

## How to add new bus message handlers

Subscribe in `handle_async_init` after the bus is connected:

```python
# After bus.connected_event.wait():
self.bus.on("ovos.some.new.event", self._on_some_event)
```

Handler pattern (runs in the bus receive thread — no `await`):

```python
def _on_some_event(self, message) -> None:
    value = message.data.get("some_key")
    for player in self.players:
        # mutate _attr_* attributes synchronously
        player._attr_volume_level = int(value * 100)
        player.update_state()   # thread-safe
```

If you need to schedule an async operation from a handler:

```python
def _on_some_event(self, message) -> None:
    asyncio.run_coroutine_threadsafe(
        self._async_handler(message.data),
        self.mass.loop
    )

async def _async_handler(self, data: dict) -> None:
    # can await here
    ...
```

---

## ProviderFeature vs PlayerFeature

`SUPPORTED_FEATURES` (module-level `set[ProviderFeature]`) is empty in this plugin because
player providers don't browse libraries. If you were building a provider that also exposes a
music library, you would add flags such as `ProviderFeature.BROWSE` or
`ProviderFeature.SEARCH`. For a pure player provider, leave `SUPPORTED_FEATURES` empty.

---

## Writing unit tests with a mock bus

### Testing command methods

```python
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from music_assistant_models.enums import PlaybackState


def make_player():
    """Build a minimal OVOSPlayer with a mock provider."""
    from ovos_ma_player import OVOSPlayer, OVOSPlayerProvider
    from ovos_bus_client import Message

    provider = MagicMock(spec=OVOSPlayerProvider)
    provider.bus = MagicMock()
    provider.Message = Message
    provider.mass = MagicMock()
    provider.mass.streams.resolve_stream_url = AsyncMock(return_value="http://stream/test.mp3")

    player = OVOSPlayer(provider, "test:ovos")
    return player, provider


@pytest.mark.asyncio
async def test_pause_emits_correct_message():
    player, provider = make_player()
    await player.pause()
    provider.bus.emit.assert_called_once()
    msg = provider.bus.emit.call_args[0][0]
    assert msg.msg_type == "ovos.common_play.pause"
    assert player._attr_playback_state == PlaybackState.PAUSED


@pytest.mark.asyncio
async def test_volume_set_emits_percent():
    player, provider = make_player()
    await player.volume_set(75)
    msg = provider.bus.emit.call_args[0][0]
    assert msg.msg_type == "mycroft.volume.set"
    assert abs(msg.data["percent"] - 0.75) < 1e-6
    assert player._attr_volume_level == 75
```

### Testing poll with a fake OVOS response

```python
@pytest.mark.asyncio
async def test_poll_updates_playback_state():
    from ovos_bus_client import Message
    player, provider = make_player()

    fake_response = Message(
        "ovos.common_play.status.response",
        {"state": "playing", "media": {"position": 42000}}   # position in ms
    )
    provider.bus.wait_for_response = MagicMock(return_value=fake_response)

    await player.poll()

    assert player._attr_playback_state == PlaybackState.PLAYING
    assert player._attr_elapsed_time == 42   # 42000 ms // 1000 = 42 s


@pytest.mark.asyncio
async def test_poll_no_response_leaves_state_unchanged():
    player, provider = make_player()
    player._attr_playback_state = PlaybackState.PLAYING
    provider.bus.wait_for_response = MagicMock(return_value=None)

    await player.poll()

    # State unchanged when OVOS doesn't respond
    assert player._attr_playback_state == PlaybackState.PLAYING
```

### Testing state event handlers

```python
def test_on_player_state_playing():
    from ovos_bus_client import Message
    from ovos_ma_player import OVOSPlayerProvider, OVOSPlayer

    provider = MagicMock(spec=OVOSPlayerProvider)
    player = OVOSPlayer(provider, "test:ovos")
    player.update_state = MagicMock()
    provider.players = [player]

    msg = Message("ovos.common_play.player.state", {"state": "playing"})
    OVOSPlayerProvider._on_player_state(provider, msg)

    assert player._attr_playback_state == PlaybackState.PLAYING
    player.update_state.assert_called_once()


def test_on_media_state_end_clears_media():
    from ovos_bus_client import Message
    from ovos_ma_player import OVOSPlayerProvider, OVOSPlayer

    provider = MagicMock(spec=OVOSPlayerProvider)
    player = OVOSPlayer(provider, "test:ovos")
    player._attr_current_media = MagicMock()
    player.update_state = MagicMock()
    provider.players = [player]

    msg = Message("ovos.common_play.media.state", {"state": "end_of_media"})
    OVOSPlayerProvider._on_media_state(provider, msg)

    assert player._attr_playback_state == PlaybackState.IDLE
    assert player._attr_current_media is None
```

### Using FakeBus for integration-level tests

`ovos-bus-client` ships `ovos_bus_client.util.FakeBus`, an in-process pub/sub bus with no
network connection. It supports `emit`, `on`, and `wait_for_response`, making it useful for
testing handler registration and end-to-end message flow without a real OVOS instance.

```python
from ovos_bus_client.util import FakeBus
from ovos_bus_client import Message

def test_fake_bus_handler_registration():
    fake = FakeBus()
    received = []
    fake.on("ovos.common_play.pause", lambda m: received.append(m))
    fake.emit(Message("ovos.common_play.pause"))
    assert len(received) == 1
    assert received[0].msg_type == "ovos.common_play.pause"
```

---

## Packaging and publishing to PyPI

### pyproject.toml requirements

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-ma-player"
version = "0.1.0"
description = "My custom Music Assistant player provider"
requires-python = ">=3.11"
dependencies = ["music-assistant-plugin-manager", "my-device-sdk"]

[project.entry-points."music_assistant.provider"]
my_player = "my_ma_player"

[tool.setuptools.packages.find]
include = ["my_ma_player*"]

[tool.setuptools.package-data]
my_ma_player = ["manifest.json"]
```

The `music-assistant-plugin-manager` dependency gives you access to `music_assistant.models`
imports without requiring a full MA server installation at build/test time.

### Directory structure

```
my-ma-player/
    pyproject.toml
    my_ma_player/
        __init__.py     # setup(), get_config_entries(), SUPPORTED_FEATURES, Provider, Player
        manifest.json
```

### Building and publishing

```bash
pip install build twine
python -m build
twine upload dist/*
```

### Versioning

Use semantic versioning. Increment the minor version for new features (new PlayerFeature flags,
new bus message handlers); increment the patch version for bug fixes.

---

## Entrypoint system in detail

When MA starts, it calls `importlib.metadata.entry_points(group="music_assistant.provider")`
to discover all installed providers. Each entry point is a `(key, module_path)` pair installed
by `pip` from your `pyproject.toml`.

MA loads each provider module lazily (when the user adds a provider instance or MA restores
saved state). It calls:

1. `module.get_config_entries(mass)` — to render the config form (or restore saved config).
2. `module.setup(mass, manifest, config)` — to instantiate the provider.
3. `provider.handle_async_init()` — the async init hook, called by MA after the event loop is
   confirmed running.
4. `provider.discover_players()` — to register player instances.

On teardown, MA calls:

1. `player.on_unload()` for each player.
2. `provider.unload()`.

`manifest.json` is located by MA using `importlib.resources` or by looking for the file
alongside the package module. It must be included in the wheel (hence the `package-data` entry
in `pyproject.toml`).
