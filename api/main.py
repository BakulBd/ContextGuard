"""ContextGuard REST API -- the machine-integration surface, alongside
the Streamlit dashboard's human-facing one. Both share the same
`contextguard` package; run ONE of them at a time against a given
camera, not both -- a webcam is exclusive-access hardware, and there
is exactly one ContextGuardPipeline per process here (see
api/state.py).

Deliberately a single-process, single-worker service. The standard
FastAPI production recipe -- `gunicorn -w 4 -k uvicorn.workers.Uvicorn
Worker` -- does NOT apply here: each worker would try to open the same
camera device and either fail outright or silently fight over frames.
If this needs to scale, put a cache in front of the read-heavy
endpoints (/events, /stream.mjpg) rather than adding workers; the
capture loop itself is the one thing that cannot be parallelized.

Run with:
    uvicorn api.main:app --host 127.0.0.1 --port 8000
    # interactive API docs at http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from contextguard.config import load_config
from contextguard.logging_setup import get_logger

from .routes import events, health, metrics, query, stream, zones
from .security import limiter
from .state import get_service, has_service, init_service

log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tests inject a fake service (api.state.set_service) before the
    # TestClient enters this lifespan, so it never touches a real camera
    # or downloads a model -- see tests/test_api.py.
    if not has_service():
        init_service(load_config())
    get_service().start()
    log.info("ContextGuard API ready.")
    try:
        yield
    finally:
        get_service().stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ContextGuard API",
        description=(
            "Structured security events, zone management, and grounded "
            "natural-language querying over a laptop-webcam context-aware "
            "monitoring pipeline. See /docs for interactive schemas."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],  # no browser cross-origin access by default; list explicit origins for a separate web frontend
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(zones.router)
    app.include_router(query.router)
    app.include_router(stream.router)
    app.include_router(metrics.router)
    return app


app = create_app()
