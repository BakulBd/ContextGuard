from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from contextguard.events import Event

from ..schemas import EventOut
from ..security import require_api_key
from ..state import get_service

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(require_api_key)])


def to_out(e: Event) -> EventOut:
    return EventOut(
        event_id=e.event_id,
        track_id=e.track_id,
        timestamp=e.timestamp,
        identity=e.identity,
        zone=e.zone,
        zone_kind=e.zone_kind,
        duration_seconds=e.duration_seconds,
        behavior=e.behavior,
        risk_score=e.risk_score,
        risk_level=e.risk_level,
        risk_breakdown=e.risk_breakdown,
        narrative=e.narrative,
    )


@router.get("", response_model=list[EventOut])
def list_events(
    time_from: str | None = None,
    time_to: str | None = None,
    min_risk: float | None = None,
    zone: str | None = None,
    identity: str | None = None,
    behavior_contains: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[EventOut]:
    store = get_service().pipeline.store
    rows = store.query(
        time_from=time_from,
        time_to=time_to,
        min_risk=min_risk,
        zone=zone,
        identity=identity,
        behavior_contains=behavior_contains,
        limit=limit,
    )
    return [to_out(e) for e in rows]


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int) -> EventOut:
    event = get_service().pipeline.store.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return to_out(event)
