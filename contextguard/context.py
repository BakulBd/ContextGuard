"""Temporal context engine.

This is where "a person is in a box" becomes "a person has been in the
restricted zone for 47 seconds, is on their third visit this hour, and
it's 2:37 AM" -- the discrete, human-checkable signals the risk engine
scores and the NLP layer narrates. Deliberately not a learned model:
every signal here is something a person could verify by looking at a
clock and a stopwatch, which is the point (see the proposal's
"interpretable by design" framing).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, time as dtime
from typing import Optional

from .zones import Zone, ZoneManager

Point = tuple[float, float]


def _parse_hhmm(s: str) -> dtime:
    hh, mm = s.split(":")
    return dtime(hour=int(hh), minute=int(mm))


def is_after_hours(now: datetime, start: str, end: str) -> bool:
    """True if `now` falls inside the [start, end) window, handling the
    overnight wrap-around (e.g. 22:00 -> 07:00) correctly.
    """
    start_t, end_t = _parse_hhmm(start), _parse_hhmm(end)
    now_t = now.time()
    if start_t <= end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t


@dataclasses.dataclass
class _Visit:
    zone: str
    zone_kind: str
    enter_ts: datetime
    exit_ts: Optional[datetime] = None


@dataclasses.dataclass
class _TrackState:
    track_id: int
    first_seen: datetime
    last_seen: datetime
    current_zone: Optional[str] = None
    current_zone_kind: Optional[str] = None
    zone_entered_at: Optional[datetime] = None
    seen_normal_zone: bool = False
    loiter_flagged: bool = False
    visits: list = dataclasses.field(default_factory=list)  # list[_Visit], completed only


@dataclasses.dataclass
class ContextSnapshot:
    track_id: int
    zone: Optional[str]
    zone_kind: Optional[str]
    dwell_seconds: float
    is_loitering: bool
    just_started_loitering: bool
    repeat_visit_count: int
    is_after_hours: bool
    abnormal_transition: bool
    zone_changed: bool
    entered_zone: Optional[str]  # set only on the frame a new zone is entered
    exited_zone: Optional[str]  # set only on the frame a zone is exited


class ContextEngine:
    def __init__(
        self,
        zones: ZoneManager,
        loiter_seconds: float = 30.0,
        repeat_visit_window_minutes: float = 60.0,
        after_hours_start: str = "22:00",
        after_hours_end: str = "07:00",
        track_expiry_seconds: float = 5.0,
    ):
        self.zones = zones
        self.loiter_seconds = loiter_seconds
        self.repeat_visit_window_minutes = repeat_visit_window_minutes
        self.after_hours_start = after_hours_start
        self.after_hours_end = after_hours_end
        self.track_expiry_seconds = track_expiry_seconds
        self._tracks: dict[int, _TrackState] = {}

    def _get_or_create(self, track_id: int, now: datetime) -> _TrackState:
        state = self._tracks.get(track_id)
        if state is None:
            state = _TrackState(track_id=track_id, first_seen=now, last_seen=now)
            self._tracks[track_id] = state
        return state

    def _repeat_visits(self, state: _TrackState, zone_name: str, now: datetime) -> int:
        window_start = now.timestamp() - self.repeat_visit_window_minutes * 60
        count = sum(
            1
            for v in state.visits
            if v.zone == zone_name and (v.exit_ts or v.enter_ts).timestamp() >= window_start
        )
        if state.current_zone == zone_name:
            count += 1  # the ongoing visit counts too
        return count

    def update(self, track_id: int, point: Point, now: Optional[datetime] = None) -> ContextSnapshot:
        now = now or datetime.now()
        state = self._get_or_create(track_id, now)
        state.last_seen = now

        zone: Optional[Zone] = self.zones.zone_for_point(point)
        zone_name = zone.name if zone else None
        zone_kind = zone.kind if zone else None

        zone_changed = zone_name != state.current_zone
        entered_zone: Optional[str] = None
        exited_zone: Optional[str] = None

        if zone_changed:
            if state.current_zone is not None:
                state.visits.append(
                    _Visit(
                        zone=state.current_zone,
                        zone_kind=state.current_zone_kind or "normal",
                        enter_ts=state.zone_entered_at or now,
                        exit_ts=now,
                    )
                )
                exited_zone = state.current_zone
            if zone_name is not None:
                entered_zone = zone_name
                state.zone_entered_at = now
                if zone_kind == "normal":
                    state.seen_normal_zone = True
            else:
                state.zone_entered_at = None
            state.current_zone = zone_name
            state.current_zone_kind = zone_kind
            state.loiter_flagged = False

        dwell_seconds = (now - state.zone_entered_at).total_seconds() if state.zone_entered_at else 0.0
        is_loitering = zone_name is not None and dwell_seconds >= self.loiter_seconds
        just_started_loitering = is_loitering and not state.loiter_flagged
        if is_loitering:
            state.loiter_flagged = True

        repeat_visit_count = self._repeat_visits(state, zone_name, now) if zone_name else 0

        # A person who has never been observed in a "normal" zone before
        # showing up in a "restricted" one skipped the expected approach
        # path -- a coarse but genuinely informative anomaly signal.
        abnormal_transition = bool(zone_kind == "restricted" and not state.seen_normal_zone and zone_changed)

        return ContextSnapshot(
            track_id=track_id,
            zone=zone_name,
            zone_kind=zone_kind,
            dwell_seconds=dwell_seconds,
            is_loitering=is_loitering,
            just_started_loitering=just_started_loitering,
            repeat_visit_count=repeat_visit_count,
            is_after_hours=is_after_hours(now, self.after_hours_start, self.after_hours_end),
            abnormal_transition=abnormal_transition,
            zone_changed=zone_changed,
            entered_zone=entered_zone,
            exited_zone=exited_zone,
        )

    def expire(self, now: Optional[datetime] = None, seen_track_ids: Optional[set[int]] = None) -> list[int]:
        """Close out tracks that vanished (left the frame, occluded past
        recovery) without a formal zone-exit update. Returns the list of
        track IDs that were expired this call.
        """
        now = now or datetime.now()
        seen_track_ids = seen_track_ids or set()
        expired: list[int] = []
        for track_id, state in list(self._tracks.items()):
            if track_id in seen_track_ids:
                continue
            if (now - state.last_seen).total_seconds() < self.track_expiry_seconds:
                continue
            if state.current_zone is not None:
                state.visits.append(
                    _Visit(
                        zone=state.current_zone,
                        zone_kind=state.current_zone_kind or "normal",
                        enter_ts=state.zone_entered_at or state.last_seen,
                        exit_ts=state.last_seen,
                    )
                )
            del self._tracks[track_id]
            expired.append(track_id)
        return expired

    def reset(self) -> None:
        self._tracks.clear()
