# ovos-ma-player

Music Assistant PlayerProvider that drives a local OVOS / OCP instance via the OVOS messagebus.

## Overview

OVOS (OpenVoiceOS) ships with OCP (OpenVoiceOS Common Play), an audio pipeline that handles
media playback through its own skill/plugin system. This package bridges Music Assistant — the
media server — with that pipeline. MA resolves audio stream URLs; this plugin translates MA
playback commands into OCP bus messages and translates OCP state events back into MA player state.

The connection is a plain WebSocket to `ws://localhost:8181/core` with no authentication. This
means both services must run on the same host, or the OVOS host must be reachable on the LAN
with port 8181 exposed.

## Key Classes

| Class | Purpose | Source |
|---|---|---|
| `OVOSPlayerProvider` | MA `PlayerProvider` — manages the bus connection and player registration | `ovos_ma_player/__init__.py:226` |
| `OVOSPlayer` | MA `Player` — translates MA commands to OCP bus messages | `ovos_ma_player/__init__.py:83` |

## Contents

- [Installation & configuration](../README.md)
- [Architecture & message reference](architecture.md)
- [Plugin authors guide](plugin-authors.md)
