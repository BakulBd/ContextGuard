"""Pydantic request/response models for the API -- the one place in
this project where Pydantic is the right tool. The rest of
``contextguard`` uses plain dataclasses (see contextguard/config.py's
docstring reasoning); here, request validation with clear 422 error
messages is exactly what FastAPI/Pydantic are for.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EventOut(BaseModel):
    event_id: int
    track_id: int
    timestamp: str
    identity: str
    zone: str | None
    zone_kind: str | None
    duration_seconds: float
    behavior: list[str]
    risk_score: float
    risk_level: str
    risk_breakdown: dict[str, float]
    narrative: str


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(restricted|normal)$")
    polygon: list[tuple[float, float]] = Field(min_length=3)


class ZoneOut(BaseModel):
    name: str
    kind: str
    polygon: list[tuple[float, float]]


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class QueryOut(BaseModel):
    text: str
    intent: str
    filters: dict
    rows: list[EventOut]


class HealthOut(BaseModel):
    status: str
    camera_open: bool
    fps: float
    frames_processed: int
    uptime_seconds: float
