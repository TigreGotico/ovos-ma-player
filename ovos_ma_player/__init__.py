"""OpenVoiceOS player provider for Music Assistant.

Connects to a local OVOS messagebus (ws://localhost:8181/core) and drives
playback via OCP bus messages — the same protocol OCP skills use.

MA controls OVOS; OVOS reports state back via bus events which are used to
keep the MA player state in sync.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry, ConfigValueType
from music_assistant_models.enums import (
    ConfigEntryType,
    PlaybackState,
    PlayerFeature,
    ProviderFeature,
)
from music_assistant_models.player import PlayerMedia

from music_assistant.models.player import Player
from music_assistant.models.player_provider import PlayerProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES: set[ProviderFeature] = set()

CONF_HOST = "host"
CONF_PORT = "port"

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8181


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    return OVOSPlayerProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    return (
        ConfigEntry(
            key=CONF_HOST,
            type=ConfigEntryType.STRING,
            label="OVOS messagebus host",
            required=False,
            default_value=DEFAULT_HOST,
            description="Hostname or IP of the OVOS messagebus. Must be reachable from MA.",
        ),
        ConfigEntry(
            key=CONF_PORT,
            type=ConfigEntryType.INTEGER,
            label="OVOS messagebus port",
            required=False,
            default_value=DEFAULT_PORT,
        ),
    )


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

class OVOSPlayer(Player):
    """MA Player backed by an OVOS OCP instance."""

    def __init__(self, provider: OVOSPlayerProvider, player_id: str) -> None:
        super().__init__(provider, player_id)
        self._attr_name = "OVOS / OCP"
        self._attr_supported_features = {
            PlayerFeature.PLAY_MEDIA,
            PlayerFeature.POWER,
            PlayerFeature.PAUSE,
            PlayerFeature.VOLUME_SET,
            PlayerFeature.VOLUME_MUTE,
            PlayerFeature.SEEK,
            PlayerFeature.PLAY_ANNOUNCEMENT,
        }
        self._attr_powered = True
        self._attr_volume_level = 50
        self._attr_volume_muted = False
        self._attr_playback_state = PlaybackState.IDLE

    @property
    def needs_poll(self) -> bool:
        return True

    @property
    def poll_interval(self) -> int:
        return 5 if self._attr_playback_state == PlaybackState.PLAYING else 30

    # ------------------------------------------------------------------
    # Playback commands — translate to OCP bus messages
    # ------------------------------------------------------------------

    async def play(self) -> None:
        await asyncio.to_thread(self.provider.bus.emit,
                                self.provider.Message("ovos.common_play.resume"))
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def pause(self) -> None:
        await asyncio.to_thread(self.provider.bus.emit,
                                self.provider.Message("ovos.common_play.pause"))
        self._attr_playback_state = PlaybackState.PAUSED
        self.update_state()

    async def stop(self) -> None:
        await asyncio.to_thread(self.provider.bus.emit,
                                self.provider.Message("ovos.common_play.stop"))
        self._attr_playback_state = PlaybackState.IDLE
        self._attr_current_media = None
        self.update_state()

    async def seek(self, position: int) -> None:
        # OCP seek takes seconds as a float
        await asyncio.to_thread(self.provider.bus.emit,
                                self.provider.Message("ovos.common_play.set_track_position",
                                                      {"position": float(position)}))

    async def volume_set(self, volume_level: int) -> None:
        # OCP doesn't have a dedicated volume message — go via the system mixer
        await asyncio.to_thread(self.provider.bus.emit,
                                self.provider.Message("mycroft.volume.set",
                                                      {"percent": volume_level / 100}))
        self._attr_volume_level = volume_level
        self.update_state()

    async def volume_mute(self, muted: bool) -> None:
        await asyncio.to_thread(self.provider.bus.emit,
                                self.provider.Message("mycroft.volume.mute" if muted
                                                      else "mycroft.volume.unmute"))
        self._attr_volume_muted = muted
        self.update_state()

    async def power(self, powered: bool) -> None:
        # OVOS doesn't have a power concept; stop on "off"
        if not powered:
            await self.stop()
        self._attr_powered = powered
        self.update_state()

    async def play_media(self, media: PlayerMedia) -> None:
        url = await self.provider.mass.streams.resolve_stream_url(self.player_id, media)
        msg = self.provider.Message("ovos.common_play.play", {
            "tracks": [{"uri": url,
                        "title": getattr(media, "title", None) or url,
                        "artist": getattr(media, "artist_name", None) or "",
                        "image": getattr(media, "image_url", None) or ""}],
        })
        await asyncio.to_thread(self.provider.bus.emit, msg)
        self._attr_current_media = media
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def play_announcement(
        self, announcement: PlayerMedia, volume_level: int | None = None
    ) -> None:
        url = await self.provider.mass.streams.resolve_stream_url(self.player_id, announcement)
        msg = self.provider.Message("ovos.common_play.play", {
            "tracks": [{"uri": url,
                        "title": getattr(announcement, "title", None) or "Announcement",
                        "artist": "",
                        "image": ""}],
        })
        await asyncio.to_thread(self.provider.bus.emit, msg)

    async def poll(self) -> None:
        """Ask OCP for current playback state."""
        def _ask():
            resp = self.provider.bus.wait_for_response(
                self.provider.Message("ovos.common_play.status"),
                reply_type="ovos.common_play.status.response",
                timeout=2.0,
            )
            return resp

        resp = await asyncio.to_thread(_ask)
        if resp:
            state = resp.data.get("state")  # "playing" / "paused" / "stopped"
            if state == "playing":
                self._attr_playback_state = PlaybackState.PLAYING
            elif state == "paused":
                self._attr_playback_state = PlaybackState.PAUSED
            else:
                self._attr_playback_state = PlaybackState.IDLE
            pos = resp.data.get("position")
            if pos is not None:
                self._attr_elapsed_time = int(pos)
            volume = resp.data.get("volume")
            if volume is not None:
                self._attr_volume_level = int(volume * 100)
        self.update_state()

    async def on_unload(self) -> None:
        await self.stop()


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class OVOSPlayerProvider(PlayerProvider):
    """Player provider that drives OVOS / OCP via the local messagebus."""

    # Imported lazily in handle_async_init
    Message = None

    async def handle_async_init(self) -> None:
        try:
            from ovos_bus_client import MessageBusClient, Message  # noqa: PLC0415
            self.Message = Message
            self._MessageBusClient = MessageBusClient
        except ImportError as err:
            from music_assistant_models.errors import ProviderUnavailableError
            raise ProviderUnavailableError("ovos-bus-client not installed") from err

        host = self.config.get_value(CONF_HOST) or DEFAULT_HOST
        port = int(self.config.get_value(CONF_PORT) or DEFAULT_PORT)

        self.bus = self._MessageBusClient(host=host, port=port,
                                          route="/core", ssl=False)
        # Run the websocket loop in a daemon thread — MA is async, the bus
        # client is synchronous websocket-based.
        t = threading.Thread(target=self.bus.run_forever, daemon=True)
        t.start()
        self.bus.connected_event.wait(timeout=10)
        if not self.bus.connected_event.is_set():
            from music_assistant_models.errors import ProviderUnavailableError
            raise ProviderUnavailableError(
                f"Could not connect to OVOS messagebus at {host}:{port}")

        self.logger.info("Connected to OVOS messagebus at %s:%s", host, port)

        # Subscribe to OCP state change events so MA stays in sync without polling
        self.bus.on("ovos.common_play.track.state", self._on_track_state)
        self.bus.on("ovos.common_play.media.state", self._on_media_state)

    def _on_track_state(self, message) -> None:
        """OCP reports a new player/track state."""
        state = message.data.get("state")
        for player in self.players:
            if state == "playing":
                player._attr_playback_state = PlaybackState.PLAYING
            elif state == "paused":
                player._attr_playback_state = PlaybackState.PAUSED
            elif state in ("stopped", "end"):
                player._attr_playback_state = PlaybackState.IDLE
                player._attr_current_media = None
            player.update_state()

    def _on_media_state(self, message) -> None:
        """OCP finished the current media item."""
        state = message.data.get("state")
        if state in ("end", "error"):
            for player in self.players:
                player._attr_playback_state = PlaybackState.IDLE
                player._attr_current_media = None
                player.update_state()

    async def discover_players(self) -> None:
        player_id = f"{self.instance_id}:ovos"
        player = OVOSPlayer(self, player_id)
        await self.mass.players.register(player)

    async def unload(self) -> None:
        if hasattr(self, "bus"):
            self.bus.close()
