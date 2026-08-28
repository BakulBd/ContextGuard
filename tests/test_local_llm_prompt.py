"""Tests for the local-LLM narrator's prompt construction only -- pure
logic, no model download or `transformers` dependency required, so
this runs in CI even without the `localllm` extra installed. Actually
loading and generating from the model is a manual/slow check, not part
of the default test suite (see tools/compare_narrators.py instead).
"""

from contextguard.events import Event
from contextguard.nlp.local_llm import build_prompt


def make_event(**overrides):
    defaults = dict(
        track_id=7,
        timestamp="2026-01-01T02:37:00",
        identity="unknown",
        zone="restricted laboratory",
        zone_kind="restricted",
        duration_seconds=47,
        behavior=["loitering"],
        risk_score=91,
        risk_level="high",
        risk_breakdown={},
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_prompt_has_system_and_user_turns():
    messages = build_prompt(make_event())
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]


def test_system_prompt_forbids_accusatory_language():
    messages = build_prompt(make_event())
    system = messages[0]["content"].lower()
    for term in ["criminal", "intruder", "suspect", "thief"]:
        assert term in system  # named explicitly as forbidden, not merely absent


def test_user_prompt_contains_only_true_facts():
    event = make_event()
    user = build_prompt(event)[1]["content"]
    assert "2:37 AM" in user
    assert "restricted laboratory" in user
    assert "unidentified" in user
    assert "47 seconds" in user  # loitering -> duration included
    assert "high" in user


def test_duration_omitted_when_not_loitering():
    event = make_event(behavior=["normal"], duration_seconds=3)
    user = build_prompt(event)[1]["content"]
    assert "duration in zone" not in user


def test_known_identity_used_verbatim():
    event = make_event(identity="Alice")
    user = build_prompt(event)[1]["content"]
    assert "identity: Alice" in user
    assert "unidentified" not in user
