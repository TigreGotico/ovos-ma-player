# Plugin Authors Guide — ovos-ma-player

This document is for developers who want to fork, extend, or use this plugin as a template for
a new Music Assistant PlayerProvider.

---

## How the MA plugin entrypoint system works

Music Assistant discovers provider plugins via the `music_assistant.provider` setuptools
entry-point group. Each entry point maps a key to a Python module:

```toml
# pyproject.toml
[project.entry-points."music_assistant.provider"]
ovos_player = "ovos_ma_player"
```

When MA loads a provider it calls two module-level functions:

1. `get_config_entries(mass, instance_id, action, values)` — returns a tuple of `ConfigEntry`
   objects that MA renders as a configuration form in the UI.
2. `setup(mass, manifest, config)` — constructs and returns the provider instance.

MA also reads `manifest.json` (co-packaged with the Python module) for metadata:
`type`, `domain`, `name`, `multi_instance`, `requirements`, etc.

`multi_instance: false` means MA will refuse to add a second instance of this provider. Set it
to `true` (and update the manifest) if your variant should support multiple simultaneous
instances.

---

## How to add new PlayerFeature flags

`OVOSPlayer.__init__` declares supported features in `_attr_supported_features`:

```python
# ovos_ma_player/__init__.py:89
self._attr_supported_features = {
    PlayerFeature.PLAY_MEDIA,
    PlayerFeature.POWER,
    PlayerFeature.PAUSE,
    PlayerFeature.VOLUME_SET,
    PlayerFeature.VOLUME_MUTE,
    PlayerFeature.SEEK,
    PlayerFeature.PLAY_ANNOUNCEMENT,
}
```

`PlayerFeature` is an enum from `music_assistant_models.enums`. To add a feature:

1. Add the flag to `_attr_supported_features`.
2. Implement the corresponding `async` method on your `Player` subclass (MA will call it when
   the feature is used).
3. Translate it to the appropriate OCP bus message in that method.

Example — adding `PlayerFeature.NEXT_PREVIOUS_TRACK`:

```python
# Add to _attr_supported_features
PlayerFeature.NEXT_PREVIOUS_TRACK,

# Implement the methods
async def next_track(self) -> None:
    await asyncio.to_thread(self.provider.bus.emit,
                            self.provider.Message("ovos.common_play.next"))

async def previous_track(self) -> None:
    await asyncio.to_thread(self.provider.bus.emit,
                            self.provider.Message("ovos.common_play.prev"))
```

Check whether OCP actually supports the message you intend to emit before advertising the
feature flag to MA.

---

## How to add new bus message handlers

Subscribe in `handle_async_init` after the bus is connected:

```python
# ovos_ma_player/__init__.py:256
self.bus.on("ovos.common_play.player.state", self._on_player_state)
self.bus.on("ovos.common_play.media.state", self._on_media_state)
```

Pattern for a new handler:

```python
# In handle_async_init, after bus is connected:
self.bus.on("ovos.some.new.event", self._on_some_event)

# Handler (called from the bus receive thread, not the asyncio loop):
def _on_some_event(self, message) -> None:
    value = message.data.get("some_key")
    for player in self.players:
        # mutate _attr_* attributes
        player.update_state()   # thread-safe, schedules on the event loop
```

Do not call `await` inside handlers — they run in the bus thread. If you need to schedule
an async operation, use `asyncio.run_coroutine_threadsafe(coro, self.mass.loop)`.

---

## ProviderFeature vs PlayerFeature

`SUPPORTED_FEATURES` at module level (`ovos_ma_player/__init__.py:34`) is a `set[ProviderFeature]`,
currently empty. `ProviderFeature` flags advertise provider-level capabilities to MA (e.g.
browsing a library). `PlayerFeature` flags (on the player) advertise per-player playback
capabilities. They are separate enums from `music_assistant_models.enums`.

---

## Testing tips

### Mock bus

`ovos-bus-client` ships `ovos_bus_client.util.FakeBus`, which is an in-process bus stub with no
network connection. You can use it to unit-test handler logic:

```python
from ovos_bus_client.util import FakeBus
from ovos_bus_client import Message

fake = FakeBus()
received = []
fake.on("ovos.common_play.pause", lambda m: received.append(m))

# Simulate MA emitting pause
fake.emit(Message("ovos.common_play.pause"))
assert len(received) == 1
```

### Fake OVOS state responses

To test `poll()`, patch `bus.wait_for_response` to return a synthetic response:

```python
from unittest.mock import MagicMock, patch
from ovos_bus_client import Message

fake_response = Message("ovos.common_play.status.response",
                        {"state": 1, "media": {"position": 42.0}})

with patch.object(provider.bus, "wait_for_response", return_value=fake_response):
    await player.poll()

assert player._attr_playback_state == PlaybackState.PLAYING
assert player._attr_elapsed_time == 42
```

### Integration test against a real OVOS

Run OVOS locally (or in a container), start MA with the plugin installed, add the provider,
and use `ovos-bus-client monitor` on the OVOS host to observe messages flowing in both
directions.
