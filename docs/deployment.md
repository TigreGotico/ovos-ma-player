# Deployment Guide — ovos-ma-player

This guide covers running `ovos-ma-player` in production environments. It assumes Music
Assistant is already installed and running. For MA installation, see the
[Music Assistant documentation](https://music-assistant.io/docs).

---

## Prerequisites

- OVOS is running with OCP active.
- The OVOS messagebus (`ws://host:8181/core`) is reachable from the MA host.
- `ovos-ma-player` is installed in MA's Python environment.

---

## Running MA on bare metal (venv)

If MA runs directly on a Linux host in a virtual environment:

```bash
# Activate MA's venv
source /opt/music-assistant/venv/bin/activate

# Install the plugin
pip install ovos-ma-player

# Restart MA
sudo systemctl restart music-assistant
```

After restart, open the MA UI, go to **Settings > Players**, and add the provider.

---

## Running MA as a Home Assistant add-on

The official Music Assistant Home Assistant add-on exposes an **Extra pip packages** field:

1. Open Home Assistant.
2. Go to **Settings > Add-ons > Music Assistant**.
3. Click **Configuration**.
4. Add `ovos-ma-player` to the **Extra pip packages** list.
5. Click **Save**, then restart the add-on.

OVOS must be reachable from the HA host on port 8181. If OVOS is on the same host as HA,
`localhost` works. If OVOS is on a separate device, use its LAN IP.

---

## Running MA in Docker

### Extending the official image

```dockerfile
FROM ghcr.io/music-assistant/server:latest
RUN pip install ovos-ma-player
```

Build and run:

```bash
docker build -t ma-with-ovos-player .
docker run -d \
  --name music-assistant \
  -p 8095:8095 \
  -v /path/to/ma-data:/data \
  ma-with-ovos-player
```

If OVOS runs on the Docker host, use the host's LAN IP (not `localhost`) as the messagebus
host in MA config. On Linux, `172.17.0.1` is typically the Docker bridge gateway; on
Mac/Windows, use `host.docker.internal`.

### docker-compose example

```yaml
version: "3.9"
services:
  music-assistant:
    build: .          # uses the Dockerfile above
    ports:
      - "8095:8095"
    volumes:
      - ma-data:/data
    restart: unless-stopped

volumes:
  ma-data:
```

---

## systemd unit for MA (bare metal)

If MA does not ship a systemd unit, create one:

```ini
[Unit]
Description=Music Assistant
After=network.target

[Service]
Type=simple
User=music-assistant
ExecStart=/opt/music-assistant/venv/bin/music-assistant start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save to `/etc/systemd/system/music-assistant.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable music-assistant
sudo systemctl start music-assistant
```

---

## OVOS configuration for remote access

If MA and OVOS are on different machines, OVOS must bind its messagebus on `0.0.0.0`.

Edit `~/.config/mycroft/mycroft.conf` on the OVOS host:

```json
{
  "websocket": {
    "host": "0.0.0.0",
    "port": 8181
  }
}
```

Restart OVOS after this change.

**Security note:** Binding on `0.0.0.0` with no authentication exposes the OVOS bus to all
machines on the local network. Anyone who can reach port 8181 can send arbitrary commands to
OVOS. Acceptable on a trusted home network; not acceptable on a shared or untrusted network.
Use `hivemind-ma-player` if you need authentication.

---

## Firewall rules

Allow MA to reach OVOS port 8181. Example using `ufw` on the OVOS host:

```bash
# Allow the MA host IP to reach the OVOS messagebus
sudo ufw allow from MA_HOST_IP to any port 8181
```

Replace `MA_HOST_IP` with the actual IP of the machine running MA.

---

## Network requirements

| Connection | Protocol | Port | Direction | Auth |
|---|---|---|---|---|
| MA -> OVOS messagebus | WebSocket (`ws://`) | 8181 | MA initiates | None |
| OVOS -> MA streams | HTTP | MA stream port (default 8095) | OVOS initiates when playing | None (internal) |

The MA stream port must be reachable from OVOS when they are on different machines. Configure
MA's network settings to use an externally reachable address for stream URLs.

---

## Version requirements

| Component | Minimum version | Notes |
|---|---|---|
| Python | 3.11 | Required by MA |
| Music Assistant | 2.x | Plugin uses `music_assistant.models` from 2.x API |
| ovos-bus-client | Any recent | Tested with 0.0.x series |
| ovos-utils | Any recent | Imported lazily for `ocp` classes |
| OVOS with OCP | Any with `ovos-skill-ocp` installed | OCP must be active |

There is no declared minimum version for `music-assistant` itself in `pyproject.toml`. If the
MA API changes in a breaking way, this plugin will need updating.

---

## Monitoring

### Check the connection is active

After MA starts, look for this log line (in MA's log output):

```
INFO  ovos_ma_player Connected to OVOS messagebus at localhost:8181
```

If you see instead:

```
ERROR Could not connect to OVOS messagebus at localhost:8181
```

OVOS is not running or the port is not reachable.

### Watch OCP messages

On the OVOS host:

```bash
ovos-bus-client monitor
```

Trigger playback from MA and watch for `ovos.common_play.play` arriving and
`ovos.common_play.player.state` being emitted.

### MA logs

MA logs to stdout and/or a log file depending on your setup. Filter for the provider:

```bash
# systemd
journalctl -u music-assistant -f | grep ovos_ma_player

# Docker
docker logs -f music-assistant | grep ovos_ma_player
```
