"""Natural-language querying of the event log.

Framed deliberately as a small task-oriented semantic-parsing problem,
not "add a chatbot": intent classification + slot extraction ->
deterministic translation into a structured filter -> retrieval ->
answer generation restricted to the retrieved rows. Intent/slot
accuracy and answer faithfulness are meant to be evaluated as two
separate numbers (see the project proposal) -- conflating "did it
understand the question" with "did it answer truthfully" hides which
half of the pipeline is actually failing.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timedelta
from typing import Optional

import dateparser

from ..config import RiskThresholds
from ..events import Event, EventStore
from .generate import EventNarrator

INTENT_COUNT = "count"
INTENT_TOP_RISK = "top_risk"
INTENT_ZONE_AGGREGATE = "zone_aggregate"
INTENT_LIST = "list"


@dataclasses.dataclass
class ParsedQuery:
    intent: str
    filters: dict
    raw_question: str


@dataclasses.dataclass
class QueryAnswer:
    parsed: ParsedQuery
    rows: list[Event]
    text: str


class NLQueryEngine:
    def __init__(
        self,
        narrator: Optional[EventNarrator] = None,
        zone_names: Optional[list[str]] = None,
        risk_thresholds: Optional[RiskThresholds] = None,
    ):
        self.narrator = narrator or EventNarrator()
        self.zone_names = zone_names or []
        self.risk_thresholds = risk_thresholds or RiskThresholds()

    # -- intent + slot parsing --------------------------------------------------

    def parse(self, question: str, now: Optional[datetime] = None) -> ParsedQuery:
        now = now or datetime.now()
        q = question.lower().strip()
        filters: dict = {}

        if re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", q):
            intent = INTENT_COUNT
        elif re.search(r"\bhighest[- ]risk\b|\bmost severe\b|\bworst\b", q):
            intent = INTENT_TOP_RISK
        elif re.search(r"\bwhich zone\b|\bmost incidents\b|\bbusiest\b", q):
            intent = INTENT_ZONE_AGGREGATE
        else:
            intent = INTENT_LIST

        if re.search(r"\bcritical\b", q):
            filters["min_risk"] = self.risk_thresholds.critical
        elif re.search(r"\bhigh[- ]?risk\b", q):
            filters["min_risk"] = self.risk_thresholds.high
        m = re.search(r"risk (?:score )?(?:above|over|>=?)\s*(\d+)", q)
        if m:
            filters["min_risk"] = int(m.group(1))

        if re.search(r"\bunknown\b|\bunidentified\b|\bunrecognized\b", q):
            filters["identity"] = "unknown"

        if "loiter" in q:
            filters["behavior_contains"] = "loitering"
        elif re.search(r"repeat(ed)? entr", q):
            filters["behavior_contains"] = "repeated_entry"

        for zone_name in self.zone_names:
            if zone_name.lower() in q:
                filters["zone"] = zone_name
                break

        time_from, time_to = self._parse_time_range(q, now)
        if time_from:
            filters["time_from"] = time_from.isoformat(timespec="seconds")
        if time_to:
            filters["time_to"] = time_to.isoformat(timespec="seconds")

        return ParsedQuery(intent=intent, filters=filters, raw_question=question)

    def _parse_time_range(self, q: str, now: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
        m = re.search(r"last (\d+)\s*(minute|hour|day)s?", q)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n)}[unit]
            return now - delta, now

        m = re.search(r"between (.+?) and (.+?)(?:[.?]|$)", q)
        if m:
            t1 = dateparser.parse(m.group(1), settings={"RELATIVE_BASE": now})
            t2 = dateparser.parse(m.group(2), settings={"RELATIVE_BASE": now})
            if t1 and t2:
                t1 = now.replace(hour=t1.hour, minute=t1.minute, second=0, microsecond=0)
                t2 = now.replace(hour=t2.hour, minute=t2.minute, second=0, microsecond=0)
                if t2 <= t1:
                    t2 += timedelta(days=1)
                return t1, t2

        if "yesterday" in q:
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)

        if "today" in q:
            return now.replace(hour=0, minute=0, second=0, microsecond=0), now

        if "after midnight" in q or "overnight" in q:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now.replace(hour=6, minute=0, second=0, microsecond=0)

        return None, None

    # -- retrieval + grounded answer --------------------------------------------

    def answer(self, question: str, store: EventStore, now: Optional[datetime] = None) -> QueryAnswer:
        parsed = self.parse(question, now=now)
        rows = store.query(**parsed.filters, limit=500)

        if parsed.intent == INTENT_COUNT:
            text = f"There were {len(rows)} matching event(s)."
        elif parsed.intent == INTENT_TOP_RISK:
            top = sorted(rows, key=lambda e: e.risk_score, reverse=True)[:1]
            rows = top
            text = self.narrator.generate_summary(top)
        elif parsed.intent == INTENT_ZONE_AGGREGATE:
            counts: dict[str, int] = {}
            for e in rows:
                if e.zone:
                    counts[e.zone] = counts.get(e.zone, 0) + 1
            if counts:
                top_zone = max(counts, key=counts.get)
                text = f"{top_zone} had the most incidents ({counts[top_zone]} of {len(rows)} matching events)."
            else:
                text = "No zone-tagged events matched that question."
        else:
            text = self.narrator.generate_summary(rows)

        return QueryAnswer(parsed=parsed, rows=rows, text=text)
