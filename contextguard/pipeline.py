"""Orchestrates one frame through the full pipeline:

    camera -> detect+track -> zone/context -> risk -> event store
            -> grounded narrative -> alert -> annotated frame

Both the headless CLI (scripts/run_headless.py) and the Streamlit
dashboard call ``ContextGuardPipeline.step()`` once per frame -- all
the actual logic lives here so the two front ends stay thin.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime

import cv2
import numpy as np

from .alerts import AlertManager
from .config import AppConfig, resolve_path
from .context import ContextEngine, ContextSnapshot
from .events import Event, EventStore
from .identity import IdentityResolver, anonymous_resolver
from .logging_setup import get_logger
from .nlp.generate import EventNarrator
from .perf import PerfMonitor
from .risk import RiskFeatures, RiskResult, create_risk_engine
from .tracking import PersonTracker, TrackedPerson
from .zones import ZoneManager

RISK_COLORS_BGR = {
    "low": (100, 170, 90),
    "medium": (40, 170, 220),
    "high": (30, 110, 220),
    "critical": (40, 40, 210),
}
NEUTRAL_COLOR_BGR = (170, 170, 170)
ZONE_OUTLINE_COLORS_BGR = {"restricted": (40, 40, 210), "normal": (150, 150, 90)}

log = get_logger("pipeline")


@dataclasses.dataclass
class FrameResult:
    frame: np.ndarray
    tracked: list[TrackedPerson]
    new_events: list[Event]
    fps: float
    avg_latency_ms: float
    cpu_percent: float
    mem_mb: float


class ContextGuardPipeline:
    def __init__(self, config: AppConfig, identity_resolver: IdentityResolver = anonymous_resolver):
        self.config = config
        self.identity_resolver = identity_resolver

        self.camera = None  # opened lazily by start(), so construction never touches hardware
        self.tracker = PersonTracker(
            model_name=config.model_name,
            device=config.device,
            conf=config.conf_threshold,
            tracker_cfg=config.tracker_cfg,
        )
        self.zones = ZoneManager.load(resolve_path(config.zones_path))
        self.context = ContextEngine(
            zones=self.zones,
            loiter_seconds=config.loiter_seconds,
            repeat_visit_window_minutes=config.repeat_visit_window_minutes,
            after_hours_start=config.after_hours_start,
            after_hours_end=config.after_hours_end,
            track_expiry_seconds=config.track_expiry_seconds,
        )
        self.risk_engine = create_risk_engine(config)
        self.store = EventStore(resolve_path(config.db_path))
        self.narrator = EventNarrator()
        self.alerts = AlertManager(
            cooldown_seconds=config.alert_cooldown_seconds,
            min_level=config.alert_risk_level,
            desktop_notifications=config.desktop_notifications,
        )
        self.perf = PerfMonitor()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        from .camera import CameraSource

        if self.camera is None:
            self.camera = CameraSource(self.config.camera_source, self.config.capture_width, self.config.capture_height)
        self.camera.open()
        log.info(
            "Pipeline started: camera='%s' model=%s risk_mode=%s zones=%d",
            self.config.camera_source, self.config.model_name, self.config.risk_mode, len(self.zones.zones),
        )

    def stop(self) -> None:
        if self.camera is not None:
            self.camera.release()
        log.info("Pipeline stopped.")

    def reload_zones(self) -> None:
        self.zones = ZoneManager.load(resolve_path(self.config.zones_path))
        self.context.zones = self.zones

    # -- per-frame step --------------------------------------------------------

    def step(self) -> FrameResult | None:
        if self.camera is None:
            self.start()
        assert self.camera is not None

        frame = self.camera.read()
        if frame is None:
            return None

        t0 = time.perf_counter()
        now = datetime.now()
        h, w = frame.shape[:2]

        seen_ids: set[int] = set()
        new_events: list[Event] = []

        try:
            people = self.tracker.update(frame)
        except Exception:
            # A single bad frame (corrupt capture, a model edge case) should
            # degrade this frame, not take down an unattended long-running
            # service -- the frame is still shown, just with no detections.
            log.exception("Detection/tracking failed on this frame; skipping detections for it.")
            people = []

        self._draw_zones(frame)

        for person in people:
            try:
                seen_ids.add(person.track_id)
                gx, gy = person.ground_point
                snapshot = self.context.update(person.track_id, (gx / w, gy / h), now)

                identity_name = self.identity_resolver(frame, person.bbox)
                identity_known = identity_name is not None
                display_identity = identity_name if identity_known else "unknown"

                behavior = self._behavior_tags(snapshot)
                features = RiskFeatures(
                    identity_known=identity_known,
                    zone_kind=snapshot.zone_kind,
                    after_hours=snapshot.is_after_hours,
                    dwell_seconds=snapshot.dwell_seconds,
                    is_loitering=snapshot.is_loitering,
                    repeat_visit_count=snapshot.repeat_visit_count,
                    abnormal_transition=snapshot.abnormal_transition,
                )
                risk = self.risk_engine.score(features)

                if snapshot.entered_zone is not None or snapshot.just_started_loitering:
                    event = self._record_event(person, display_identity, snapshot, behavior, risk, now)
                    new_events.append(event)

                self._draw_person(frame, person, snapshot, risk)
            except Exception:
                log.exception("Failed processing track_id=%s this frame; continuing with other tracks.", person.track_id)

        self.context.expire(now, seen_ids)

        dt = time.perf_counter() - t0
        self.perf.tick(dt)

        return FrameResult(
            frame=frame,
            tracked=people,
            new_events=new_events,
            fps=self.perf.fps,
            avg_latency_ms=self.perf.avg_latency_ms,
            cpu_percent=self.perf.cpu_percent(),
            mem_mb=self.perf.mem_mb(),
        )

    # -- internals ---------------------------------------------------------

    def _behavior_tags(self, snapshot: ContextSnapshot) -> list[str]:
        tags = []
        if snapshot.is_loitering:
            tags.append("loitering")
        if snapshot.repeat_visit_count >= self.config.repeat_visit_threshold:
            tags.append("repeated_entry")
        if snapshot.is_after_hours:
            tags.append("after_hours")
        if snapshot.abnormal_transition:
            tags.append("abnormal_transition")
        return tags or ["normal"]

    def _record_event(
        self,
        person: TrackedPerson,
        identity: str,
        snapshot: ContextSnapshot,
        behavior: list[str],
        risk: RiskResult,
        now: datetime,
    ) -> Event:
        event = Event(
            track_id=person.track_id,
            timestamp=now.isoformat(timespec="seconds"),
            identity=identity,
            zone=snapshot.zone,
            zone_kind=snapshot.zone_kind,
            duration_seconds=snapshot.dwell_seconds,
            behavior=behavior,
            risk_score=risk.score,
            risk_level=risk.level,
            risk_breakdown=risk.breakdown,
        )
        event.narrative = self.narrator.generate(event)
        self.store.add_event(event)

        if self.alerts.should_fire(person.track_id, risk.level):
            self.alerts.fire(f"ContextGuard: {risk.level.upper()} risk", event.narrative)

        return event

    def _draw_zones(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        for zone in self.zones.zones:
            pts = np.array([[int(x * w), int(y * h)] for x, y in zone.polygon], dtype=np.int32)
            color = ZONE_OUTLINE_COLORS_BGR.get(zone.kind, NEUTRAL_COLOR_BGR)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, dst=frame)
            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)
            label_pos = tuple(pts[0])
            cv2.putText(frame, zone.name, label_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

    def _draw_person(
        self, frame: np.ndarray, person: TrackedPerson, snapshot: ContextSnapshot, risk: RiskResult
    ) -> None:
        x1, y1, x2, y2 = (int(v) for v in person.bbox)
        color = RISK_COLORS_BGR.get(risk.level, NEUTRAL_COLOR_BGR) if snapshot.zone else NEUTRAL_COLOR_BGR
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = f"Person #{person.track_id}"
        if snapshot.zone:
            label += f" | {snapshot.zone} | risk {int(risk.score)}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv2.putText(frame, label, (x1 + 3, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (15, 15, 15), 1, cv2.LINE_AA)
