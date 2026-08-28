#!/usr/bin/env bash
# Production entrypoint for machines without systemd (macOS, a minimal
# Linux box). Binds to localhost only, disables Streamlit's telemetry
# and auto-open-browser behavior, and restarts on crash with a backoff
# so a transient failure (camera hiccup, an unhandled exception) doesn't
# take monitoring down for good.
#
# On systemd machines, prefer deploy/*.service instead -- Restart=
# there does the same job with proper process supervision and logging
# to the journal.
#
# Usage:
#   ./scripts/serve.sh
#   CONTEXTGUARD_DASHBOARD_PASSWORD=... ./scripts/serve.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ -z "${CONTEXTGUARD_DASHBOARD_PASSWORD:-}" ]; then
  echo "WARNING: CONTEXTGUARD_DASHBOARD_PASSWORD is not set." >&2
  echo "The dashboard will run unauthenticated. Fine for 127.0.0.1-only access; not fine if this host is reachable from anywhere else." >&2
fi

RETRY_DELAY=5
MAX_RETRY_DELAY=60

while true; do
  echo "$(date -Iseconds) starting ContextGuard dashboard..."
  .venv/bin/streamlit run dashboard/app.py \
    --server.address=127.0.0.1 \
    --server.port=8501 \
    --server.headless=true \
    --browser.gatherUsageStats=false \
    && break  # a clean exit (e.g. Ctrl-C) shouldn't be treated as a crash

  echo "$(date -Iseconds) dashboard exited unexpectedly; restarting in ${RETRY_DELAY}s..." >&2
  sleep "$RETRY_DELAY"
  RETRY_DELAY=$(( RETRY_DELAY * 2 < MAX_RETRY_DELAY ? RETRY_DELAY * 2 : MAX_RETRY_DELAY ))
done
