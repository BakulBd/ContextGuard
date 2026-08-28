from datetime import datetime, timedelta

from contextguard.events import Event, EventStore


def make_event(**overrides):
    defaults = dict(
        track_id=1,
        timestamp="2026-01-01T02:37:00",
        identity="unknown",
        zone="vault",
        zone_kind="restricted",
        duration_seconds=47,
        behavior=["loitering"],
        risk_score=87,
        risk_level="critical",
        risk_breakdown={"restricted-zone entry": 30},
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_add_and_retrieve(tmp_path):
    store = EventStore(tmp_path / "events.db")
    event_id = store.add_event(make_event())
    assert event_id == 1

    rows = store.query()
    assert len(rows) == 1
    assert rows[0].zone == "vault"
    assert rows[0].behavior == ["loitering"]
    assert rows[0].risk_breakdown == {"restricted-zone entry": 30}


def test_query_filters(tmp_path):
    store = EventStore(tmp_path / "events.db")
    store.add_event(make_event(zone="vault", risk_score=90, timestamp="2026-01-01T02:00:00"))
    store.add_event(
        make_event(zone="lobby", zone_kind="normal", behavior=["normal"], risk_score=10, timestamp="2026-01-01T09:00:00")
    )

    high_risk = store.query(min_risk=50)
    assert len(high_risk) == 1 and high_risk[0].zone == "vault"

    lobby_only = store.query(zone="lobby")
    assert len(lobby_only) == 1

    morning_only = store.query(time_from="2026-01-01T05:00:00")
    assert len(morning_only) == 1 and morning_only[0].zone == "lobby"

    loitering_only = store.query(behavior_contains="loitering")
    assert len(loitering_only) == 1 and loitering_only[0].zone == "vault"


def test_update_narrative(tmp_path):
    store = EventStore(tmp_path / "events.db")
    event_id = store.add_event(make_event())
    store.update_narrative(event_id, "A test narrative.")
    assert store.query()[0].narrative == "A test narrative."


def test_zone_incident_counts(tmp_path):
    store = EventStore(tmp_path / "events.db")
    store.add_event(make_event(zone="vault"))
    store.add_event(make_event(zone="vault"))
    store.add_event(make_event(zone="lobby", zone_kind="normal", behavior=["normal"]))
    counts = store.zone_incident_counts()
    assert counts["vault"] == 2
    assert counts["lobby"] == 1


def test_purge_older_than(tmp_path):
    store = EventStore(tmp_path / "events.db")
    now = datetime.now()
    store.add_event(make_event(timestamp=(now - timedelta(days=400)).isoformat(timespec="seconds")))
    store.add_event(make_event(timestamp=(now - timedelta(hours=1)).isoformat(timespec="seconds")))

    removed = store.purge_older_than(days=30)
    assert removed == 1
    assert len(store.query()) == 1


def test_recent_uses_minutes_window(tmp_path):
    store = EventStore(tmp_path / "events.db")
    now = datetime.now()
    store.add_event(make_event(timestamp=(now - timedelta(minutes=90)).isoformat(timespec="seconds")))
    store.add_event(make_event(timestamp=(now - timedelta(minutes=5)).isoformat(timespec="seconds")))

    recent = store.recent(minutes=30)
    assert len(recent) == 1
