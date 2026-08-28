"""Person detection and tracking.

Uses Ultralytics YOLOv8n for detection. For tracking, Ultralytics
ships ByteTrack (and BoT-SORT) built in via ``model.track(...)`` --
this project uses that instead of pulling in a separate `supervision`
dependency, because it's the same ByteTrack algorithm the project
proposal specifies, with one less package to keep working across
Python versions.

Two classes are exposed on purpose:

- ``PersonDetector``: detection only, no persistence of IDs across
  frames. Used by tools/benchmark_detector.py to measure the
  detector's own cost in isolation from tracking overhead -- the
  proposal is explicit that published FPS numbers conflate the two
  and that needs to be pulled apart on the actual target laptop.
- ``PersonTracker``: detection + ByteTrack association, persistent
  track IDs. This is what the live pipeline uses.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from ultralytics import YOLO

from .geometry import ground_point

COCO_PERSON_CLASS = 0


@dataclasses.dataclass
class Detection:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    confidence: float


@dataclasses.dataclass
class TrackedPerson:
    track_id: int
    bbox: tuple[float, float, float, float]
    confidence: float

    @property
    def ground_point(self) -> tuple[float, float]:
        return ground_point(self.bbox)


class PersonDetector:
    """Detection-only wrapper, for benchmarking and for anyone who
    wants detection without the tracker's association overhead.
    """

    def __init__(self, model_name: str = "yolov8n.pt", device: str = "cpu", conf: float = 0.35):
        self.model = YOLO(model_name)
        self.device = device
        self.conf = conf

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model.predict(
            frame,
            classes=[COCO_PERSON_CLASS],
            conf=self.conf,
            device=self.device,
            verbose=False,
        )
        out: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                xyxy = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                out.append(Detection(bbox=tuple(xyxy), confidence=conf))
        return out


class PersonTracker:
    """Detection + ByteTrack, exposing persistent per-person track IDs.

    ``reset()`` clears track history (e.g. when the user changes the
    zone layout or restarts monitoring) so old IDs don't leak into a
    new session.
    """

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        device: str = "cpu",
        conf: float = 0.35,
        tracker_cfg: str = "bytetrack.yaml",
    ):
        self.model = YOLO(model_name)
        self.device = device
        self.conf = conf
        self.tracker_cfg = tracker_cfg

    def update(self, frame: np.ndarray) -> list[TrackedPerson]:
        results = self.model.track(
            frame,
            classes=[COCO_PERSON_CLASS],
            conf=self.conf,
            device=self.device,
            tracker=self.tracker_cfg,
            persist=True,
            verbose=False,
        )
        people: list[TrackedPerson] = []
        for r in results:
            if r.boxes is None or r.boxes.id is None:
                continue
            ids = r.boxes.id.int().tolist()
            for box, track_id in zip(r.boxes, ids):
                xyxy = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                people.append(TrackedPerson(track_id=int(track_id), bbox=tuple(xyxy), confidence=conf))
        return people

    def reset(self) -> None:
        # Ultralytics keeps tracker state on the predictor object; the
        # cleanest reset is to drop it and let the next .track() call
        # lazily recreate a fresh tracker.
        self.model.predictor = None
