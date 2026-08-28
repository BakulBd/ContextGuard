from contextguard.events import Event
from contextguard.nlp.generate import EventNarrator, check_grounding, format_clock, format_duration


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


def test_format_clock():
    assert format_clock("2026-01-01T02:37:00") == "2:37 AM"
    assert format_clock("2026-01-01T14:05:00") == "2:05 PM"
    assert format_clock("2026-01-01T00:00:00") == "12:00 AM"


def test_format_duration_seconds_vs_minutes():
    assert "47 seconds" in format_duration(47)
    assert "minute" in format_duration(130)


def test_narrator_generates_grounded_sentence():
    narrator = EventNarrator(seed=1)
    event = make_event()
    text = narrator.generate(event)

    assert "restricted laboratory" in text
    assert "2:37 AM" in text
    assert any(w in text for w in ("unidentified", "unknown", "unrecognized"))

    report = check_grounding(text, event)
    assert report.passed is True
    assert report.disallowed_terms_found == []


def test_narrator_never_uses_accusatory_language():
    narrator = EventNarrator(seed=2)
    text = narrator.generate(make_event(risk_level="critical"))
    lowered = text.lower()
    for term in ["criminal", "intruder", "suspect", "thief"]:
        assert term not in lowered


def test_grounding_check_flags_wrong_zone():
    event = make_event()
    bad = "At 2:37 AM, an unidentified person entered the server room and remained there for approximately 47 seconds."
    report = check_grounding(bad, event)
    assert report.passed is False
    assert report.entity_ok is False


def test_grounding_check_flags_wrong_duration():
    event = make_event()
    bad = (
        "At 2:37 AM, an unidentified person entered the restricted laboratory "
        "and remained there for approximately 400 seconds."
    )
    report = check_grounding(bad, event)
    assert report.passed is False
    assert report.numeric_ok is False


def test_grounding_check_flags_disallowed_terms():
    event = make_event()
    bad = "At 2:37 AM, an intruder entered the restricted laboratory."
    report = check_grounding(bad, event)
    assert report.passed is False
    assert "intruder" in report.disallowed_terms_found


def test_grounding_check_passes_correct_alternative_phrasing():
    event = make_event()
    good = "At 2:37 AM, an unknown individual walked into the restricted laboratory and stayed for about 47 seconds."
    report = check_grounding(good, event)
    assert report.passed is True


def test_generate_summary_single_vs_multi_event():
    narrator = EventNarrator(seed=3)
    single = narrator.generate_summary([make_event()])
    assert "restricted laboratory" in single

    multi = narrator.generate_summary(
        [make_event(risk_score=40, risk_level="medium"), make_event(risk_score=91, risk_level="high", zone="lobby", zone_kind="normal")]
    )
    assert "2 matching events" in multi
    assert "highest-risk" in multi


def test_generate_summary_empty():
    narrator = EventNarrator(seed=4)
    assert "No matching events" in narrator.generate_summary([])
