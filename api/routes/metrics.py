"""Prometheus scrape endpoint. Behind the same API-key/loopback rule as
everything else -- Prometheus supports a bearer token or custom header
in its scrape config (`authorization:` / `headers:` in the job spec),
so this doesn't have to mean opening it up.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from ..security import require_api_key
from ..state import get_service

router = APIRouter(tags=["metrics"], dependencies=[Depends(require_api_key)])

FPS_GAUGE = Gauge("contextguard_fps", "Current processing frames per second")
CPU_GAUGE = Gauge("contextguard_cpu_percent", "Capture process CPU percent")
MEM_GAUGE = Gauge("contextguard_memory_mb", "Capture process RSS memory, in MB")
UPTIME_GAUGE = Gauge("contextguard_uptime_seconds", "Seconds since the capture loop started")
FRAMES_COUNTER = Counter("contextguard_frames_processed_total", "Total frames processed since process start")
EVENTS_GAUGE = Gauge("contextguard_events_total", "Total events currently in the event store")

_last_frame_count = 0


@router.get("/metrics")
def metrics() -> Response:
    global _last_frame_count
    service = get_service()
    stats = service.stats()

    FPS_GAUGE.set(stats["fps"])
    CPU_GAUGE.set(stats["cpu_percent"])
    MEM_GAUGE.set(stats["mem_mb"])
    UPTIME_GAUGE.set(stats["uptime_seconds"])

    delta = stats["frames_processed"] - _last_frame_count
    if delta > 0:
        FRAMES_COUNTER.inc(delta)
    _last_frame_count = stats["frames_processed"]

    EVENTS_GAUGE.set(service.pipeline.store.count())

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
