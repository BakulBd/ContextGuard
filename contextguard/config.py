"""Central configuration for ContextGuard.

Everything the pipeline needs to know that isn't hard-coded lives here:
camera source, detector/tracker choice, risk thresholds, retention, and
where the event database and zone definitions are stored on disk.

Loaded once at startup from ``config.yaml`` (created with sane defaults
on first run if it doesn't exist yet) and passed around as a plain
dataclass instead of a global.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclasses.dataclass
class RiskThresholds:
    """Cutoffs that turn a 0-100 risk score into a human-facing level.

    Not arbitrary in the deployed sense of "made up for this demo" --
    these are the *default* cutoffs and are expected to be revisited
    once real labeled data exists (see tools/train_risk_model.py and
    the risk-engine comparison in the project proposal).
    """

    medium: int = 30
    high: int = 60
    critical: int = 85

    def level_for(self, score: float) -> str:
        if score >= self.critical:
            return "critical"
        if score >= self.high:
            return "high"
        if score >= self.medium:
            return "medium"
        return "low"


@dataclasses.dataclass
class AppConfig:
    # -- camera --
    camera_source: str = "0"  # "0"/"1" (webcam index) or an rtsp:// URL
    capture_width: int = 640
    capture_height: int = 480

    # -- detection / tracking --
    # YOLO26n over YOLOv8n: ~2x faster CPU/ONNX inference (38.9ms vs 80.4ms)
    # at HIGHER accuracy (40.9 vs 37.3 mAP) per Ultralytics' own published
    # benchmark (arXiv 2605.24831) -- a straight upgrade for a CPU-only
    # deployment, and a drop-in one (same ultralytics.YOLO API). Still
    # re-verify with tools/benchmark_detector.py on the actual deployment
    # laptop before trusting any published number, per the project's own
    # "evaluate, don't blindly pick" methodology -- the flag is there for
    # exactly that comparison.
    model_name: str = "yolo26n.pt"
    device: str = "cpu"
    conf_threshold: float = 0.35
    tracker_cfg: str = "bytetrack.yaml"

    # -- NLP narration backend --
    # "template": deterministic, zero extra dependencies (default).
    # "local_llm": a small local instruct model via transformers -- opt-in,
    # needs `pip install -e ".[localllm]"`. See nlp/local_llm.py.
    narrator_backend: str = "template"
    local_llm_model: str = "HuggingFaceTB/SmolLM2-360M-Instruct"

    # -- context engine --
    loiter_seconds: float = 30.0
    repeat_visit_window_minutes: float = 60.0
    repeat_visit_threshold: int = 2
    after_hours_start: str = "22:00"
    after_hours_end: str = "07:00"
    track_expiry_seconds: float = 5.0

    # -- risk engine --
    risk_mode: str = "rule"  # "rule" | "weighted" | "ml"
    risk_thresholds: RiskThresholds = dataclasses.field(default_factory=RiskThresholds)
    weighted_weights_path: str = "data/risk_weights.json"
    ml_model_path: str = "data/risk_model.joblib"

    # -- alerts --
    alert_cooldown_seconds: float = 60.0
    alert_risk_level: str = "high"  # minimum level that fires a desktop alert
    desktop_notifications: bool = True

    # -- storage / privacy --
    db_path: str = "data/contextguard.db"
    zones_path: str = "data/zones.json"
    retention_days: int = 30
    store_thumbnails: bool = False
    blur_faces_in_thumbnails: bool = True

    # -- identity mode --
    identity_mode: str = "anonymous"  # "anonymous" | "enrolled"
    enrollment_path: str = "data/enrollment"


def _merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in (overrides or {}).items():
        if key == "risk_thresholds" and isinstance(value, dict):
            merged[key] = {**defaults.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config.yaml, filling in defaults for anything not specified.

    Creates the file with defaults on first run so the repo is usable
    out of the box with just ``python -m contextguard`` / the dashboard.
    """
    path = Path(path)
    defaults = dataclasses.asdict(AppConfig())

    if not path.exists():
        save_config(AppConfig(), path)
        raw: dict[str, Any] = {}
    else:
        raw = yaml.safe_load(path.read_text()) or {}

    merged = _merge(defaults, raw)
    thresholds = RiskThresholds(**merged.pop("risk_thresholds"))
    config = AppConfig(risk_thresholds=thresholds, **merged)
    config = apply_env_overrides(config)

    DEFAULT_DATA_DIR.mkdir(exist_ok=True)
    return config


_ENV_PREFIX = "CONTEXTGUARD_"


def _coerce(value: str, current: Any) -> Any:
    if isinstance(current, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def apply_env_overrides(config: AppConfig) -> AppConfig:
    """Let a deployment environment (a systemd unit, a container) override
    individual settings without editing config.yaml, e.g.::

        CONTEXTGUARD_CAMERA_SOURCE=1
        CONTEXTGUARD_RISK_MODE=weighted
        CONTEXTGUARD_RETENTION_DAYS=14

    Nested ``risk_thresholds`` fields aren't covered -- those change
    rarely enough to just edit config.yaml directly.
    """
    for f in dataclasses.fields(config):
        if f.name == "risk_thresholds":
            continue
        env_name = _ENV_PREFIX + f.name.upper()
        if env_name in os.environ:
            current = getattr(config, f.name)
            setattr(config, f.name, _coerce(os.environ[env_name], current))
    return config


def save_config(config: AppConfig, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dataclasses.asdict(config)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def resolve_path(relative: str) -> Path:
    """Resolve a config-relative path (e.g. 'data/contextguard.db') against the repo root."""
    p = Path(relative)
    return p if p.is_absolute() else REPO_ROOT / p
