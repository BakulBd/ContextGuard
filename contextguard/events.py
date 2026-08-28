"""Structured event storage.

Per the privacy-by-design requirement, this is the thing that gets
retained -- not continuous raw video. Every row is a discrete,
human-reviewable observation, never a verdict (see nlp/generate.py's
grounding checker for the enforcement side of that rule).
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id        INTEGER NOT NULL,
    timestamp       TEXT NOT NULL,          -- ISO 8601, local time
    identity        TEXT NOT NULL,          -- 'unknown' or an enrolled name
    zone            TEXT,
    zone_kind       TEXT,                   -- 'restricted' | 'normal' | NULL
    duration_seconds REAL NOT NULL DEFAULT 0,
    behavior        TEXT,                   -- comma-separated tags, e.g. "loitering,after_hours"
    risk_score      REAL NOT NULL,
    risk_level      TEXT NOT NULL,
    risk_breakdown  TEXT,                   -- JSON: {"factor": points, ...}
    narrative       TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_risk ON events(risk_score);
CREATE INDEX IF NOT EXISTS idx_events_zone ON events(zone);
"""


@dataclasses.dataclass
class Event:
    track_id: int
    timestamp: str  # ISO 8601
    identity: str
    zone: Optional[str]
    zone_kind: Optional[str]
    duration_seconds: float
    behavior: list[str]
    risk_score: float
    risk_level: str
    risk_breakdown: dict[str, int]
    narrative: str = ""
    event_id: Optional[int] = None
    created_at: Optional[str] = None

    def behavior_str(self) -> str:
        return ",".join(self.behavior)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> "Event":
        return Event(
            event_id=row["event_id"],
            track_id=row["track_id"],
            timestamp=row["timestamp"],
            identity=row["identity"],
            zone=row["zone"],
            zone_kind=row["zone_kind"],
            duration_seconds=row["duration_seconds"],
            behavior=(row["behavior"] or "").split(",") if row["behavior"] else [],
            risk_score=row["risk_score"],
            risk_level=row["risk_level"],
            risk_breakdown=json.loads(row["risk_breakdown"] or "{}"),
            narrative=row["narrative"] or "",
            created_at=row["created_at"],
        )


class EventStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def add_event(self, event: Event) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            """INSERT INTO events
               (track_id, timestamp, identity, zone, zone_kind, duration_seconds,
                behavior, risk_score, risk_level, risk_breakdown, narrative, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.track_id,
                event.timestamp,
                event.identity,
                event.zone,
                event.zone_kind,
                event.duration_seconds,
                event.behavior_str(),
                event.risk_score,
                event.risk_level,
                json.dumps(event.risk_breakdown),
                event.narrative,
                now,
            ),
        )
        self._conn.commit()
        event.event_id = cur.lastrowid
        event.created_at = now
        return cur.lastrowid

    def get(self, event_id: int) -> Optional[Event]:
        row = self._conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return Event._row_to_event(row) if row else None

    def update_narrative(self, event_id: int, narrative: str) -> None:
        self._conn.execute("UPDATE events SET narrative = ? WHERE event_id = ?", (narrative, event_id))
        self._conn.commit()

    def query(
        self,
        time_from: Optional[str] = None,
        time_to: Optional[str] = None,
        min_risk: Optional[float] = None,
        max_risk: Optional[float] = None,
        zone: Optional[str] = None,
        identity: Optional[str] = None,
        behavior_contains: Optional[str] = None,
        order: str = "desc",
        limit: int = 200,
    ) -> list[Event]:
        clauses: list[str] = []
        params: list[Any] = []
        if time_from:
            clauses.append("timestamp >= ?")
            params.append(time_from)
        if time_to:
            clauses.append("timestamp <= ?")
            params.append(time_to)
        if min_risk is not None:
            clauses.append("risk_score >= ?")
            params.append(min_risk)
        if max_risk is not None:
            clauses.append("risk_score <= ?")
            params.append(max_risk)
        if zone:
            clauses.append("zone LIKE ?")
            params.append(f"%{zone}%")
        if identity:
            clauses.append("identity LIKE ?")
            params.append(f"%{identity}%")
        if behavior_contains:
            clauses.append("behavior LIKE ?")
            params.append(f"%{behavior_contains}%")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_sql = "DESC" if order == "desc" else "ASC"
        sql = f"SELECT * FROM events {where} ORDER BY timestamp {order_sql} LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [Event._row_to_event(r) for r in rows]

    def recent(self, minutes: int = 30, limit: int = 200) -> list[Event]:
        since = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        return self.query(time_from=since, limit=limit)

    def zone_incident_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT zone, COUNT(*) as n FROM events WHERE zone IS NOT NULL GROUP BY zone ORDER BY n DESC"
        ).fetchall()
        return {r["zone"]: r["n"] for r in rows}

    def count(self, **filters: Any) -> int:
        return len(self.query(limit=10_000, **filters))

    def purge_older_than(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        cur = self._conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
