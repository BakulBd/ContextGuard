"""Camera abstraction.

The MVP requirement is just index 0 (the laptop's built-in webcam).
This wrapper accepts anything OpenCV's VideoCapture accepts so a USB
webcam (a different integer index) or an RTSP/IP camera (a string
URL) work through the identical interface later without touching any
downstream code -- per the brief, camera source is a config value,
not an architectural fork.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from .logging_setup import get_logger

log = get_logger("camera")


@dataclass
class CameraInfo:
    source: str
    width: int
    height: int
    fps: float


class CameraError(RuntimeError):
    pass


class CameraSource:
    """Thin, restart-able wrapper around cv2.VideoCapture.

    ``source`` may be:
      - "0", "1", ... -> local camera index (webcam / USB camera)
      - "rtsp://..." or any URL/path OpenCV's backend understands
    """

    def __init__(
        self,
        source: str = "0",
        width: int = 640,
        height: int = 480,
        reconnect_after_failures: int = 15,
        reconnect_backoff_seconds: float = 3.0,
    ):
        self.source_str = source
        self.width = width
        self.height = height
        self.reconnect_after_failures = reconnect_after_failures
        self.reconnect_backoff_seconds = reconnect_backoff_seconds
        self._cap: cv2.VideoCapture | None = None
        self._consecutive_failures = 0
        self._last_reconnect_attempt = 0.0

    def _open(self) -> cv2.VideoCapture:
        source: str | int = int(self.source_str) if self.source_str.isdigit() else self.source_str
        cap = cv2.VideoCapture(source)
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not cap.isOpened():
            raise CameraError(
                f"Could not open camera source '{self.source_str}'. "
                "If this is a webcam index, confirm no other app is using it "
                "and that the current user has permission to access /dev/video*."
            )
        return cap

    def open(self) -> "CameraSource":
        if self._cap is None:
            self._cap = self._open()
        return self

    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> np.ndarray | None:
        """Return the next BGR frame, or None if the read failed.

        Never raises on a transient read failure (webcam hiccups are
        expected in the field) -- callers should treat None as "skip
        this tick," not as a fatal error. After enough consecutive
        failures (device unplugged, another app grabbed it, a laptop
        sleep/wake cycle), automatically attempts to reopen the device
        on a backoff -- important for a long-running unattended
        deployment, where nobody is there to restart the process by hand.
        """
        if self._cap is None:
            self.open()
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self._consecutive_failures += 1
            self._maybe_reconnect()
            return None
        self._consecutive_failures = 0
        return frame

    def _maybe_reconnect(self) -> None:
        if self._consecutive_failures < self.reconnect_after_failures:
            return
        now = time.monotonic()
        if now - self._last_reconnect_attempt < self.reconnect_backoff_seconds:
            return
        self._last_reconnect_attempt = now
        log.warning(
            "Camera '%s' failed %d consecutive reads -- attempting to reopen the device.",
            self.source_str,
            self._consecutive_failures,
        )
        try:
            self.release()
            self.open()
            self._consecutive_failures = 0
            log.info("Camera '%s' reopened successfully.", self.source_str)
        except CameraError as exc:
            log.warning("Reconnect attempt failed (%s); will retry after backoff.", exc)

    def info(self) -> CameraInfo:
        if self._cap is None:
            self.open()
        assert self._cap is not None
        return CameraInfo(
            source=self.source_str,
            width=int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(self._cap.get(cv2.CAP_PROP_FPS)) or 0.0,
        )

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "CameraSource":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.release()


def probe(source: str = "0", attempts: int = 3, delay: float = 0.3) -> CameraInfo | None:
    """Best-effort camera probe used by setup/benchmark scripts.

    Returns None instead of raising so a "no camera available" sandbox
    (e.g. a CI runner) can fall back to synthetic frames gracefully.
    """
    cam = CameraSource(source)
    for _ in range(attempts):
        try:
            cam.open()
            frame = cam.read()
            if frame is not None:
                info = cam.info()
                cam.release()
                return info
        except CameraError:
            return None
        time.sleep(delay)
    cam.release()
    return None
