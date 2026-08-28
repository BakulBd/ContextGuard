"""API tests use a fake PipelineService (api.state.set_service) instead
of a real camera/model -- see api/state.py's has_service()/set_service()
seam, added specifically so this suite doesn't need a webcam or a
downloaded YOLO model to exercise routing, auth, and validation.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from api import state
from contextguard.config import AppConfig, RiskThresholds
from contextguard.events import Event, EventStore
from contextguard.zones import Zone, ZoneManager


class FakePipeline:
    def __init__(self, config, store, zones):
        self.config = config
        self.store = store
        self.zones = zones
        self.camera = None
        self.reload_calls = 0

    def reload_zones(self) -> None:
        self.reload_calls += 1


class FakeService:
    def __init__(self, config, store, zones):
        self.config = config
        self.pipeline = FakePipeline(config, store, zones)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def stats(self) -> dict:
        return {"fps": 12.3, "cpu_percent": 5.0, "mem_mb": 100.0, "frames_processed": 42, "uptime_seconds": 10.0}

    def latest_frame(self):
        return None

    @property
    def is_running(self) -> bool:
        return True


def make_event(**overrides):
    defaults = dict(
        track_id=1,
        timestamp="2026-01-01T02:37:00",
        identity="unknown",
        zone="vault",
        zone_kind="restricted",
        duration_seconds=47,
        behavior=["loitering"],
        risk_score=91,
        risk_level="critical",
        risk_breakdown={"restricted-zone entry": 30},
    )
    defaults.update(overrides)
    return Event(**defaults)


@pytest.fixture
def api_key():
    key = "test-api-key-12345"
    os.environ["CONTEXTGUARD_API_KEY"] = key
    yield key
    os.environ.pop("CONTEXTGUARD_API_KEY", None)


@pytest.fixture
def client(tmp_path, api_key):
    state.reset_service()

    store = EventStore(tmp_path / "events.db")
    store.add_event(make_event())
    zones = ZoneManager(zones=[Zone("vault", "restricted", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])])
    config = AppConfig(risk_thresholds=RiskThresholds())

    state.set_service(FakeService(config, store, zones))

    from api.main import app

    with TestClient(app) as c:
        yield c

    state.reset_service()


# -- health: unauthenticated on purpose --------------------------------------

def test_healthz_needs_no_auth(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_true_once_frames_processed(client):
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["ready"] is True  # FakeService reports frames_processed=42


# -- auth ---------------------------------------------------------------

def test_protected_route_rejects_missing_key(client):
    assert client.get("/events").status_code == 401


def test_protected_route_rejects_wrong_key(client):
    assert client.get("/events", headers={"X-API-Key": "wrong"}).status_code == 401


def test_protected_route_accepts_correct_key(client, api_key):
    resp = client.get("/events", headers={"X-API-Key": api_key})
    assert resp.status_code == 200


def test_loopback_allowed_when_no_key_configured(client, monkeypatch):
    monkeypatch.delenv("CONTEXTGUARD_API_KEY", raising=False)
    monkeypatch.setattr("api.security._is_loopback", lambda request: True)
    assert client.get("/events").status_code == 200


def test_non_loopback_rejected_when_no_key_configured(client, monkeypatch):
    monkeypatch.delenv("CONTEXTGUARD_API_KEY", raising=False)
    monkeypatch.setattr("api.security._is_loopback", lambda request: False)
    assert client.get("/events").status_code == 403


# -- events ---------------------------------------------------------------

def test_list_events(client, api_key):
    resp = client.get("/events", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["zone"] == "vault"
    assert body[0]["risk_level"] == "critical"


def test_get_event_by_id(client, api_key):
    listed = client.get("/events", headers={"X-API-Key": api_key}).json()
    event_id = listed[0]["event_id"]
    resp = client.get(f"/events/{event_id}", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["event_id"] == event_id


def test_get_event_not_found(client, api_key):
    resp = client.get("/events/999999", headers={"X-API-Key": api_key})
    assert resp.status_code == 404


def test_events_min_risk_filter(client, api_key):
    resp = client.get("/events", headers={"X-API-Key": api_key}, params={"min_risk": 95})
    assert resp.status_code == 200
    assert resp.json() == []


# -- zones ---------------------------------------------------------------

def test_list_zones(client, api_key):
    resp = client.get("/zones", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert any(z["name"] == "vault" for z in resp.json())


def test_create_zone(client, api_key):
    payload = {"name": "lobby", "kind": "normal", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    resp = client.post("/zones", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 201
    assert resp.json()["name"] == "lobby"


def test_create_zone_rejects_too_few_points(client, api_key):
    payload = {"name": "bad", "kind": "normal", "polygon": [[0, 0], [1, 1]]}
    resp = client.post("/zones", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 422


def test_create_zone_rejects_bad_kind(client, api_key):
    payload = {"name": "bad", "kind": "dangerous", "polygon": [[0, 0], [1, 0], [1, 1]]}
    resp = client.post("/zones", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 422


def test_delete_zone(client, api_key):
    assert client.delete("/zones/vault", headers={"X-API-Key": api_key}).status_code == 204
    assert client.delete("/zones/vault", headers={"X-API-Key": api_key}).status_code == 404


# -- query ---------------------------------------------------------------

def test_query_endpoint_grounded_in_store(client, api_key):
    resp = client.post(
        "/query",
        headers={"X-API-Key": api_key},
        json={"question": "How many unknown people entered the restricted zone?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "count"
    assert "1" in body["text"]


def test_query_rejects_empty_question(client, api_key):
    resp = client.post("/query", headers={"X-API-Key": api_key}, json={"question": ""})
    assert resp.status_code == 422


# -- stream/metrics ---------------------------------------------------------------

def test_frame_jpg_503_when_no_frame_yet(client, api_key):
    resp = client.get("/frame.jpg", headers={"X-API-Key": api_key})
    assert resp.status_code == 503


def test_metrics_is_prometheus_formatted(client, api_key):
    resp = client.get("/metrics", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert "contextguard_fps" in resp.text
