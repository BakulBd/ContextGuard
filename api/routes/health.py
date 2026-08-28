"""Liveness/readiness -- unauthenticated on purpose, the same way a
Kubernetes/systemd health probe or a load balancer's check needs to be
reachable without a credential.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import HealthOut
from ..state import get_service

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthOut)
def healthz() -> HealthOut:
    """Liveness: is the process up and the capture loop alive."""
    service = get_service()
    stats = service.stats()
    camera = service.pipeline.camera
    return HealthOut(
        status="ok" if service.is_running else "capture_stopped",
        camera_open=bool(camera and camera.is_open()),
        fps=stats["fps"],
        frames_processed=stats["frames_processed"],
        uptime_seconds=stats["uptime_seconds"],
    )


@router.get("/readyz")
def readyz() -> dict:
    """Readiness: has at least one frame actually been processed yet --
    distinct from liveness, since the capture thread can be alive while
    still waiting on the very first camera read."""
    stats = get_service().stats()
    return {"ready": stats["frames_processed"] > 0}
