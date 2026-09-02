"""Unit tests for the pydantic-backed helper functions in ovos_ma_player.

These tests do not require a live OVOS messagebus or Music Assistant.
Only ovos-pydantic-models (and its transitive deps) must be installed.

All Music Assistant types are stubbed via unittest.mock so the module can be
imported in a plain Python environment.
"""

import sys
import types
import unittest
from enum import Enum
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Minimal stubs so ovos_ma_player can be imported without music-assistant
# ---------------------------------------------------------------------------

def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


class _PlaybackState(str, Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"


class _PlayerFeature(str, Enum):
    PLAY_MEDIA = "play_media"
    POWER = "power"
    PAUSE = "pause"
    VOLUME_SET = "volume_set"
    VOLUME_MUTE = "volume_mute"
    SEEK = "seek"
    PLAY_ANNOUNCEMENT = "play_announcement"


class _ConfigEntryType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    SECURE_STRING = "secure_string"


_stub("music_assistant")
_stub("music_assistant.models")
_stub("music_assistant.models.player", Player=object)
_stub("music_assistant.models.player_provider", PlayerProvider=object)
_stub("music_assistant.mass")
_stub("music_assistant_models")
_stub("music_assistant_models.config_entries", ConfigEntry=object, ConfigValueType=object)
_stub("music_assistant_models.enums",
      PlaybackState=_PlaybackState,
      PlayerFeature=_PlayerFeature,
      ProviderFeature=Enum("ProviderFeature", {}),
      ConfigEntryType=_ConfigEntryType)
_stub("music_assistant_models.player", PlayerMedia=object)
_stub("music_assistant_models.provider", ProviderManifest=object)
_stub("music_assistant_models.errors", ProviderUnavailableError=Exception)
_stub("ovos_bus_client", MessageBusClient=MagicMock, Message=MagicMock)

from ovos_ma_player import (  # noqa: E402  (imports after stub setup)
    _make_ocp_media_entry,
    _make_play_payload,
    _parse_player_state,
    _parse_media_state_end,
    _parse_status_response,
)

PlaybackState = _PlaybackState


# ---------------------------------------------------------------------------
# _parse_player_state
# ---------------------------------------------------------------------------

class TestParsePlayerState(unittest.TestCase):
    """`ovos.common_play.player.state` carries the int PlayerState value."""

    def test_playing(self):
        self.assertEqual(_parse_player_state({"state": 1}), PlaybackState.PLAYING)

    def test_paused(self):
        self.assertEqual(_parse_player_state({"state": 2}), PlaybackState.PAUSED)

    def test_stopped(self):
        self.assertEqual(_parse_player_state({"state": 0}), PlaybackState.IDLE)

    def test_string_name_is_also_accepted(self):
        self.assertEqual(_parse_player_state({"state": "playing"}), PlaybackState.PLAYING)

    def test_unknown_state_is_idle(self):
        self.assertEqual(_parse_player_state({"state": "flying"}), PlaybackState.IDLE)

    def test_missing_state_gives_none(self):
        self.assertIsNone(_parse_player_state({}))

    def test_null_state_gives_none(self):
        self.assertIsNone(_parse_player_state({"state": None}))


# ---------------------------------------------------------------------------
# _parse_media_state_end
# ---------------------------------------------------------------------------

class TestParseMediaStateEnd(unittest.TestCase):
    """OcpMediaState: END_OF_MEDIA=7, INVALID_MEDIA=8 (rest are non-terminal)."""

    def test_end_of_media_is_terminal(self):
        self.assertTrue(_parse_media_state_end({"state": 7}))

    def test_invalid_media_is_terminal(self):
        self.assertTrue(_parse_media_state_end({"state": 8}))

    def test_buffered_media_is_not_terminal(self):
        self.assertFalse(_parse_media_state_end({"state": 6}))

    def test_buffering_media_is_not_terminal(self):
        self.assertFalse(_parse_media_state_end({"state": 5}))

    def test_unknown_is_zero(self):
        self.assertFalse(_parse_media_state_end({"state": 0}))

    def test_string_state_is_not_valid_returns_false(self):
        self.assertFalse(_parse_media_state_end({"state": "end"}))

    def test_empty_payload_returns_false(self):
        self.assertFalse(_parse_media_state_end({}))


# ---------------------------------------------------------------------------
# _parse_status_response
# ---------------------------------------------------------------------------

class TestParseStatusResponse(unittest.TestCase):
    """The snapshot uses the int PlayerState vocabulary of ovos_utils.ocp."""

    def test_playing(self):
        self.assertEqual(_parse_status_response({"player_state": 1}), PlaybackState.PLAYING)

    def test_paused(self):
        self.assertEqual(_parse_status_response({"player_state": 2}), PlaybackState.PAUSED)

    def test_stopped(self):
        self.assertEqual(_parse_status_response({"player_state": 0}), PlaybackState.IDLE)

    def test_full_daemon_snapshot(self):
        snapshot = {
            "playback_type": 2, "media_type": 2, "player_state": 1, "loop_state": 0,
            "media_state": 3, "shuffle": False, "playlist_position": 0,
            "playlist_size": 1, "title": "Track", "artist": "Artist", "image": "",
        }
        self.assertEqual(_parse_status_response(snapshot), PlaybackState.PLAYING)

    def test_empty_gives_none(self):
        self.assertIsNone(_parse_status_response({}))

    def test_unparseable_payload_gives_none(self):
        self.assertIsNone(_parse_status_response({"player_state": "not-a-state"}))


# ---------------------------------------------------------------------------
# _make_ocp_media_entry
# ---------------------------------------------------------------------------

def _fake_media(title="Track", artist="Artist", duration=180, image="http://img"):
    m = MagicMock()
    m.title = title
    m.artist_name = artist
    m.duration = duration
    m.image_url = image
    return m


class TestMakeOcpMediaEntry(unittest.TestCase):

    def test_uri_preserved(self):
        entry = _make_ocp_media_entry("http://example.com/a.mp3", _fake_media())
        self.assertEqual(entry["uri"], "http://example.com/a.mp3")

    def test_title_and_artist(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media(title="T", artist="A"))
        self.assertEqual(entry["title"], "T")
        self.assertEqual(entry["artist"], "A")

    def test_duration_converted_to_milliseconds(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media(duration=90))
        self.assertEqual(entry["length"], 90_000)

    def test_zero_duration_when_none(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media(duration=None))
        self.assertEqual(entry["length"], 0)

    def test_title_falls_back_to_url_when_none(self):
        url = "http://x.com/a.mp3"
        entry = _make_ocp_media_entry(url, _fake_media(title=None))
        self.assertEqual(entry["title"], url)

    def test_skill_id_is_music_assistant(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media())
        self.assertEqual(entry["skill_id"], "music_assistant")

    def test_playback_is_audio(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media())
        self.assertEqual(entry["playback"], 2)

    def test_media_type_is_music(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media())
        self.assertEqual(entry["media_type"], 2)

    def test_match_confidence_is_max(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3", _fake_media())
        self.assertEqual(entry["match_confidence"], 1.0)

    def test_image_url_passed_through(self):
        entry = _make_ocp_media_entry("http://x.com/a.mp3",
                                       _fake_media(image="http://img/cover.jpg"))
        self.assertEqual(entry["image"], "http://img/cover.jpg")


# ---------------------------------------------------------------------------
# _make_play_payload
# ---------------------------------------------------------------------------

SAMPLE_ENTRY = {
    "uri": "http://example.com/stream.mp3",
    "title": "Track",
    "artist": "Artist",
    "playback": 2,
    "media_type": 2,
    "match_confidence": 1.0,
    "skill_id": "music_assistant",
    "length": 180_000,
}


class TestMakePlayPayload(unittest.TestCase):

    def test_media_field_present(self):
        payload = _make_play_payload(SAMPLE_ENTRY)
        self.assertIn("media", payload)

    def test_disambiguation_field_present_and_empty(self):
        payload = _make_play_payload(SAMPLE_ENTRY)
        self.assertIn("disambiguation", payload)
        self.assertEqual(payload["disambiguation"], [])

    def test_playlist_field_present_and_contains_entry(self):
        payload = _make_play_payload(SAMPLE_ENTRY)
        self.assertIn("playlist", payload)
        self.assertEqual(len(payload["playlist"]), 1)

    def test_media_uri_matches_entry(self):
        payload = _make_play_payload(SAMPLE_ENTRY)
        self.assertEqual(payload["media"]["uri"], SAMPLE_ENTRY["uri"])

    def test_playlist_entry_uri_matches(self):
        payload = _make_play_payload(SAMPLE_ENTRY)
        self.assertEqual(payload["playlist"][0]["uri"], SAMPLE_ENTRY["uri"])

    def test_roundtrip_through_pydantic(self):
        from ovos_pydantic_models.skills.ocp import OvosCommonPlayPlayData
        payload = _make_play_payload(SAMPLE_ENTRY)
        # Must deserialise back without error
        restored = OvosCommonPlayPlayData(**payload)
        self.assertEqual(str(restored.media["uri"]), SAMPLE_ENTRY["uri"])


if __name__ == "__main__":
    unittest.main()
