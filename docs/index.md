# ovos-ma-player

Music Assistant PlayerProvider that drives a local OVOS / OCP instance via the OVOS messagebus.

## Overview

OVOS (OpenVoiceOS) ships with OCP (OpenVoiceOS Common Play), an audio pipeline that handles
media playback through its own skill/plugin system. This package bridges Music Assistant — the
media server — with that pipeline. MA resolves audio stream URLs; this plugin translates MA
playback commands into OCP bus messages and translates OCP state events back into MA player
state.

The connection is a plain WebSocket to `ws://localhost:8181/core` (no authentication). Both
services must run on the same host, or the OVOS messagebus must be reachable on the LAN with
port 8181 exposed. If you need authentication or want to control a remote OVOS device, use
[hivemind-ma-player](https://github.com/TigreGotico/hivemind-ma-player) instead.

## Relationship to hivemind-ma-player

Both providers implement the same OCP protocol — the same set of bus messages, the same state
machine, the same `MediaEntry` serialization. The difference is entirely in the transport layer:

| | ovos-ma-player | hivemind-ma-player |
|---|---|---|
| Transport | Plain WebSocket `ws://host:8181` | Encrypted WebSocket `wss://host:5678` |
| Authentication | None | Access key + optional password |
| Multiple OVOS devices | Not supported (single instance) | Supported (`multi_instance: true`) |
| Use case | OVOS on the same machine as MA | OVOS on a remote device |
| Dependencies | `ovos-bus-client` | `ovos-bus-client` + `hivemind-bus-client` |

If you are reading the source of one, you understand the other. The architecture documents
for both packages describe the same concepts; the HiveMind package's docs note where behaviour
differs.

## Key Classes

| Class | Purpose | Source |
|---|---|---|
| `OVOSPlayerProvider` | MA `PlayerProvider` — manages the bus connection, registers players, and handles state events | `ovos_ma_player/__init__.py:301` |
| `OVOSPlayer` | MA `Player` — translates MA commands to OCP bus messages; implements polling | `ovos_ma_player/__init__.py:178` |

## Contents

- [Installation, Quick Start, Configuration & Troubleshooting](../README.md)
- [Architecture, Threading Model & OCP Message Reference](architecture.md)
- [Plugin Authors Guide — extending and testing](plugin-authors.md)
- [OCP Protocol Reference](ocp-protocol.md)
- [Deployment Guide](deployment.md)
