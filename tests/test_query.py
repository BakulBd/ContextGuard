from datetime import datetime, timedelta

from contextguard.config import RiskThresholds
from contextguard.events import Event, EventStore
from contextguard.nlp.query import INTENT_COUNT, INTENT_TOP_RISK, INTENT_ZONE_AGGREGATE, NLQueryEngine


def make_event(**overrides):
    defaults = dict(
        track_id=1,
        timestamp="2026-01-01T02:37:00",
        identity="unknown",
        zone="restricted laboratory",
        zone_kind="restricted",
        duration_seconds=47,
        behavior=["loitering"],
        risk_score=91,
        risk_level="critical",
        risk_breakdown={},
    )
    defaults.update(overrides)
    return Event(**defaults)


# -- intent / slot parsing -------------------------------------------------

def test_parse_intent_count_and_identity_slot():
    parsed = NLQueryEngine().parse("How many unknown people entered the restricted zone?")
    assert parsed.intent == INTENT_COUNT
    assert parsed.filters.get("identity") == "unknown"


def test_parse_high_risk_slot():
    engine = NLQueryEngine(risk_thresholds=RiskThresholds(high=60))
    now = datetime(2026, 1, 1, 10, 0, 0)
    parsed = engine.parse("Were there any high-risk events after midnight?", now=now)
    assert parsed.filters["min_risk"] == 60
    assert parsed.filters["time_from"] == now.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
    assert parsed.filters["time_to"] == now.replace(hour=6, minute=0, second=0).isoformat(timespec="seconds")


def test_parse_last_n_minutes():
    now = datetime(2026, 1, 1, 10, 0, 0)
    parsed = NLQueryEngine().parse("What happened in the last 30 minutes?", now=now)
    assert parsed.filters["time_from"] == (now - timedelta(minutes=30)).isoformat(timespec="seconds")


def test_parse_zone_aggregate_intent():
    parsed = NLQueryEngine().parse("Which zone had the most incidents?")
    assert parsed.intent == INTENT_ZONE_AGGREGATE


def test_parse_named_zone_slot():
    engine = NLQueryEngine(zone_names=["restricted laboratory", "lobby"])
    parsed = engine.parse("Show me events in the lobby today.")
    assert parsed.filters.get("zone") == "lobby"


def test_parse_explicit_risk_threshold():
    parsed = NLQueryEngine().parse("List events with risk score above 75")
    assert parsed.filters["min_risk"] == 75


# -- retrieval + grounded answer -------------------------------------------

def test_answer_top_risk_is_grounded_in_retrieved_row(tmp_path):
    store = EventStore(tmp_path / "events.db")
    store.add_event(make_event(risk_score=91, risk_level="critical"))
    store.add_event(make_event(zone="lobby", zone_kind="normal", behavior=["normal"], risk_score=5, risk_level="low"))

    engine = NLQueryEngine(zone_names=["restricted laboratory", "lobby"], risk_thresholds=RiskThresholds(high=60))
    result = engine.answer("Show me the highest-risk event today.", store, now=datetime(2026, 1, 1, 12, 0, 0))

    assert result.parsed.intent == INTENT_TOP_RISK
    assert len(result.rows) == 1
    assert result.rows[0].zone == "restricted laboratory"
    assert "restricted laboratory" in result.text


def test_answer_count_with_no_matches_says_so(tmp_path):
    store = EventStore(tmp_path / "events.db")
    result = NLQueryEngine().answer("How many unknown people entered the restricted zone?", store)
    assert "0" in result.text


def test_answer_zone_aggregate(tmp_path):
    store = EventStore(tmp_path / "events.db")
    store.add_event(make_event(zone="vault"))
    store.add_event(make_event(zone="vault"))
    store.add_event(make_event(zone="lobby", zone_kind="normal", behavior=["normal"], risk_score=5, risk_level="low"))

    result = NLQueryEngine(zone_names=["vault", "lobby"]).answer("Which zone had the most incidents?", store)
    assert "vault" in result.text
