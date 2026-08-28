"""Local alerting only -- an on-screen flag plus a best-effort desktop
notification, with a per-track cooldown so one lingering person doesn't
spam ten alerts a minute. External services (Telegram, email) are
explicitly out of scope for the core demo per the project brief; this
module never talks to anything off the local machine.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from .logging_setup import get_logger

log = get_logger("alerts")

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class AlertManager:
    cooldown_seconds: float = 60.0
    min_level: str = "high"
    desktop_notifications: bool = True
    _last_fired: dict[int, float] = field(default_factory=dict, repr=False)

    def should_fire(self, track_id: int, level: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        if _LEVEL_RANK.get(level, 0) < _LEVEL_RANK.get(self.min_level, 2):
            return False
        last = self._last_fired.get(track_id)
        if last is not None and (now - last) < self.cooldown_seconds:
            return False
        self._last_fired[track_id] = now
        return True

    def fire(self, title: str, message: str) -> None:
        log.warning("%s: %s", title, message)
        if self.desktop_notifications:
            notify_desktop(title, message)

    def reset(self) -> None:
        self._last_fired.clear()


def notify_desktop(title: str, message: str) -> bool:
    """Best-effort local desktop notification. Never raises -- a missing
    notify-send binary (common on minimal/headless environments) just
    means the console log in AlertManager.fire is the only alert, which
    is an acceptable degradation, not a crash.
    """
    system = platform.system()
    try:
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", "critical", title, message], check=False, timeout=2)
            return True
        if system == "Darwin" and shutil.which("osascript"):
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=2)
            return True
        if system == "Windows":
            try:
                from win10toast import ToastNotifier  # optional; not a hard dependency

                ToastNotifier().show_toast(title, message, duration=5, threaded=True)
                return True
            except ImportError:
                return False
    except Exception:
        return False
    return False
