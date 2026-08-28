from datetime import datetime, timedelta

from contextguard.context import ContextEngine, is_after_hours
from contextguard.zones import Zone, ZoneManager

LOBBY = Zone("lobby", "normal", [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)])
VAULT = Zone("vault", "restricted", [(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)])
LOBBY_POINT = (0.25, 0.5)
VAULT_POINT = (0.75, 0.5)


def make_engine(**overrides) -> ContextEngine:
    zones = ZoneManager(zones=[LOBBY, VAULT])
    defaults = dict(loiter_seconds=30.0, repeat_visit_window_minutes=60.0, track_expiry_seconds=5.0)
    defaults.update(overrides)
    return ContextEngine(zones, **defaults)


# -- after-hours window, including overnight wrap-around ---------------------

def test_after_hours_wraps_midnight():
    assert is_after_hours(datetime(2026, 1, 1, 23, 30), "22:00", "07:00") is True
    assert is_after_hours(datetime(2026, 1, 1, 3, 0), "22:00", "07:00") is True
    assert is_after_hours(datetime(2026, 1, 1, 12, 0), "22:00", "07:00") is False


def test_after_hours_non_wrapping_window():
    assert is_after_hours(datetime(2026, 1, 1, 10, 0), "09:00", "17:00") is True
    assert is_after_hours(datetime(2026, 1, 1, 20, 0), "09:00", "17:00") is False


# -- dwell time and loitering -------------------------------------------------

def test_loitering_flag_crosses_once():
    engine = make_engine()
    t0 = datetime(2026, 1, 1, 10, 0, 0)

    snap = engine.update(1, VAULT_POINT, t0)
    assert snap.zone == "vault" and snap.is_loitering is False

    snap = engine.update(1, VAULT_POINT, t0 + timedelta(seconds=31))
    assert snap.is_loitering is True
    assert snap.just_started_loitering is True

    snap = engine.update(1, VAULT_POINT, t0 + timedelta(seconds=36))
    assert snap.is_loitering is True
    assert snap.just_started_loitering is False  # already flagged once


# -- zone transitions, repeat visits, abnormal transition --------------------

def test_repeat_visit_counts_prior_plus_ongoing():
    engine = make_engine()
    t0 = datetime(2026, 1, 1, 10, 0, 0)

    engine.update(2, LOBBY_POINT, t0)
    snap = engine.update(2, VAULT_POINT, t0 + timedelta(seconds=5))
    assert snap.entered_zone == "vault" and snap.exited_zone == "lobby"
    assert snap.abnormal_transition is False  # came from a normal zone first

    engine.update(2, LOBBY_POINT, t0 + timedelta(seconds=10))
    snap = engine.update(2, VAULT_POINT, t0 + timedelta(seconds=15))
    assert snap.entered_zone == "vault"
    assert snap.repeat_visit_count == 2  # the earlier completed visit + this ongoing one


def test_abnormal_transition_direct_to_restricted():
    engine = make_engine()
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    snap = engine.update(3, VAULT_POINT, t0)  # never seen a normal zone
    assert snap.abnormal_transition is True


def test_no_abnormal_transition_flag_on_second_entry():
    engine = make_engine()
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    engine.update(4, VAULT_POINT, t0)
    engine.update(4, LOBBY_POINT, t0 + timedelta(seconds=5))
    snap = engine.update(4, VAULT_POINT, t0 + timedelta(seconds=10))
    assert snap.abnormal_transition is False  # not the first restricted entry


# -- track expiry --------------------------------------------------------

def test_expire_removes_stale_track_and_resets_state():
    engine = make_engine(track_expiry_seconds=5.0)
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    engine.update(5, VAULT_POINT, t0)

    expired = engine.expire(t0 + timedelta(seconds=10), seen_track_ids=set())
    assert expired == [5]

    snap = engine.update(5, VAULT_POINT, t0 + timedelta(seconds=11))
    assert snap.dwell_seconds == 0.0
    assert snap.zone_changed is True  # fresh state: None -> "vault" again


def test_expire_ignores_currently_seen_tracks():
    engine = make_engine(track_expiry_seconds=5.0)
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    engine.update(6, VAULT_POINT, t0)
    expired = engine.expire(t0 + timedelta(seconds=10), seen_track_ids={6})
    assert expired == []
