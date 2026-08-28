"""Shared application state: the single running ContextGuardPipeline,
its background capture thread, and the most recent annotated frame for
the snapshot/MJPEG endpoints.

Deliberately a module-level singleton rather than a per-request object
-- there is exactly one camera and exactly one pipeline per process, by
hardware necessity (see api/main.py's docstring on why this service
runs single-worker). FastAPI route handlers reach it via
``get_service()``.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from contextguard.config import AppConfig
from contextguard.logging_setup import get_logger
from contextguard.pipeline import ContextGuardPipeline

log = get_logger("api.state")


class PipelineService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.pipeline = ContextGuardPipeline(config)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_fps = 0.0
        self._latest_cpu = 0.0
        self._latest_mem = 0.0
        self._started_at = 0.0
        self._frame_count = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self.pipeline.start()
        self._stop.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="contextguard-capture", daemon=True)
        self._thread.start()
        log.info("Capture thread started.")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.pipeline.step()
            except Exception:
                log.exception("Unhandled error in capture loop; continuing after a short pause.")
                time.sleep(0.5)
                continue
            if result is None:
                time.sleep(0.05)
                continue
            with self._frame_lock:
                self._latest_frame = result.frame
                self._latest_fps = result.fps
                self._latest_cpu = result.cpu_percent
                self._latest_mem = result.mem_mb
                self._frame_count += 1

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.pipeline.stop()
        log.info("Capture thread stopped.")

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def stats(self) -> dict:
        with self._frame_lock:
            return {
                "fps": self._latest_fps,
                "cpu_percent": self._latest_cpu,
                "mem_mb": self._latest_mem,
                "frames_processed": self._frame_count,
                "uptime_seconds": (time.time() - self._started_at) if self._started_at else 0.0,
            }

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


_service: Optional[PipelineService] = None


def get_service() -> PipelineService:
    if _service is None:
        raise RuntimeError("Pipeline service not initialized -- did the app lifespan run?")
    return _service


def init_service(config: AppConfig) -> PipelineService:
    global _service
    _service = PipelineService(config)
    return _service


def has_service() -> bool:
    return _service is not None


def set_service(service: PipelineService) -> None:
    """Test hook: inject a fake/stub service (duck-typed to the same
    surface as PipelineService) so tests can exercise the API without a
    real camera or a downloaded model. api/main.py's lifespan checks
    ``has_service()`` and, if one is already set, uses it instead of
    building a real ``ContextGuardPipeline``.
    """
    global _service
    _service = service


def reset_service() -> None:
    """Test hook: drop the singleton so a fresh one can be injected."""
    global _service
    _service = None
