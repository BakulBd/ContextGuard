# Deploying ContextGuard as a standing service

Three paths, pick based on your machine: systemd (native, most control),
Docker (isolated, easiest to reproduce), or the plain restart-loop
script (no systemd, no Docker).

## systemd (Linux with systemd — most distros)

```bash
# 1. Install into a stable location (not required to be /opt, but pick
#    a path you won't move) and set it up as in the main README.
cd /path/to/ContextGuard
python3 -m venv .venv && .venv/bin/pip install -e .

# 2. Create your secrets/overrides file.
cp .env.example .env
$EDITOR .env   # at minimum, set CONTEXTGUARD_DASHBOARD_PASSWORD

# 3. Edit the placeholder paths in the unit files.
sed -i "s#YOUR_USERNAME#$(whoami)#; s#/path/to/ContextGuard#$(pwd)#" \
  deploy/contextguard-dashboard.service deploy/contextguard-purge.service

# 4. Install as user services (no root needed) -- omit --user and use
#    sudo + /etc/systemd/system/ instead if you want this to run
#    independent of any login session.
mkdir -p ~/.config/systemd/user
cp deploy/contextguard-dashboard.service deploy/contextguard-purge.service \
   deploy/contextguard-purge.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now contextguard-dashboard.service
systemctl --user enable --now contextguard-purge.timer

# 5. Check it's actually up.
systemctl --user status contextguard-dashboard.service
journalctl --user -u contextguard-dashboard.service -f
```

Dashboard is now at `http://127.0.0.1:8501`, survives reboots
(`enable`), and restarts automatically on crash (`Restart=on-failure`
in the unit file). The purge timer runs `tools/purge_old_events.py`
daily to enforce `retention_days` from config.yaml, so retention is
actually enforced instead of being a config value nobody acts on.

**Camera access as a systemd service**: the unit intentionally does
*not* set `PrivateDevices=` or `DeviceAllow=` — either would hide
`/dev/video0` from the service and break detection with a confusing
"could not open camera" error instead of a security warning. `User=`
just needs to be an account already in the `video` group (check with
`groups $(whoami)`).

## No systemd (macOS, a minimal box)

```bash
cp .env.example .env
$EDITOR .env
./scripts/serve.sh
```

Restarts on crash with a backoff, binds to `127.0.0.1` only, and
disables Streamlit's telemetry/auto-open-browser behavior. Run it
under `screen`/`tmux`, or wrap it with `launchd` on macOS (an `.plist`
calling `scripts/serve.sh` with `KeepAlive=true` is the equivalent of
the systemd unit above) if you want it to survive a logout.

## Docker (the REST API service, Linux hosts)

**Not build-tested** — no Docker available in the sandbox this project
was built in, unlike everything else in this repo (see the main
README's "Verified, not assumed" section). The `Dockerfile` follows
the same CPU-only-torch-first install order already confirmed to work
locally and in CI, so it should build cleanly, but treat the first
build on your machine as the actual test, not a formality.

```bash
cp .env.example .env
$EDITOR .env   # set CONTEXTGUARD_API_KEY at minimum -- required for anything
               # beyond the container's own host to call the API

# find your host's `video` group GID so the container's non-root user can open /dev/video0
echo "VIDEO_GID=$(getent group video | cut -d: -f3)" >> .env

docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

Restarts automatically (`restart: unless-stopped`), health-checked
(`HEALTHCHECK` in the `Dockerfile`), and the event database persists
in `./data` on the host via the bind mount in `docker-compose.yml`.

**Camera passthrough only works on a Linux Docker host.** Docker
Desktop on macOS/Windows runs containers inside a Linux VM that
generally cannot see a USB webcam at all — on those platforms, either
run the API natively (`uvicorn api.main:app`, see the main README) or
point `CONTEXTGUARD_CAMERA_SOURCE` at an `rtsp://` source reachable
over the network instead of a local device index.

Retention purge in a container: run it as a one-off alongside the
main service, e.g. from a host cron entry:

```bash
docker compose run --rm contextguard-api python tools/purge_old_events.py
```

## Exposing this beyond localhost

Don't point a router/reverse-proxy port-forward straight at Streamlit.
If you need remote access, put a real TLS-terminating reverse proxy
(Caddy, nginx, Tailscale) in front of `127.0.0.1:8501`, and make sure
`CONTEXTGUARD_DASHBOARD_PASSWORD` is set — the dashboard's password
gate is a basic shared-secret check, not a substitute for TLS or a
real auth provider. This is a research/small-deployment security
camera feed; treat its exposure surface accordingly.
