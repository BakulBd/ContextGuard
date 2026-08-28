"""API authentication and request-rate limiting.

Mirrors the dashboard's philosophy (dashboard/app.py): no key
configured means "trusted to localhost only," not "open to anyone."
A request without a valid API key is accepted only from loopback;
every other request needs an ``X-API-Key`` header matching
``CONTEXTGUARD_API_KEY``.

Rate limiting is in-memory (slowapi's default backend) -- correct for
this service's actual deployment shape (single process, single camera,
see api/main.py) and deliberately not Redis-backed, since there is
only ever one process to share state across.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from contextguard.logging_setup import get_logger

log = get_logger("api.security")

_API_KEY_ENV = "CONTEXTGUARD_API_KEY"

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else None
    return host in ("127.0.0.1", "::1", "localhost")


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    configured_key = os.environ.get(_API_KEY_ENV)

    if not configured_key:
        if _is_loopback(request):
            return
        client = request.client.host if request.client else "unknown"
        log.warning("Rejected non-loopback request from %s -- no CONTEXTGUARD_API_KEY configured.", client)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No API key configured; only localhost is trusted. Set CONTEXTGUARD_API_KEY to allow other clients.",
        )

    if not x_api_key or not hmac.compare_digest(x_api_key, configured_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-API-Key header.")
