"""Lightweight performance monitor -- smoothed FPS, CPU%, RAM. Used by
the live pipeline's on-screen performance panel and by
tools/benchmark_detector.py, so both report numbers computed the same
way (the deployment-metrics section of the project proposal only means
something if "FPS" is measured consistently).
"""

from __future__ import annotations

from collections import deque

import psutil


class PerfMonitor:
    def __init__(self, window: int = 30):
        self._durations: deque[float] = deque(maxlen=window)
        self._process = psutil.Process()
        self._process.cpu_percent(interval=None)  # prime psutil's internal counter

    def tick(self, duration_seconds: float) -> None:
        self._durations.append(duration_seconds)

    @property
    def fps(self) -> float:
        if not self._durations:
            return 0.0
        avg = sum(self._durations) / len(self._durations)
        return 1.0 / avg if avg > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        if not self._durations:
            return 0.0
        return (sum(self._durations) / len(self._durations)) * 1000.0

    def cpu_percent(self) -> float:
        """Process CPU%, not system-wide -- can exceed 100 on a multi-core
        box if the process is using more than one core."""
        return self._process.cpu_percent(interval=None)

    def mem_mb(self) -> float:
        return self._process.memory_info().rss / (1024 * 1024)
