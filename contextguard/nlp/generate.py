"""Grounded event -> natural language generation.

Every sentence produced here must be checkable against the structured
event it came from. ``check_grounding`` is both a runtime safety net
(the narrator's own output should always pass it) and the reusable
evaluator for the template vs. small-local-model vs. LLM comparison
described in the project proposal -- run it on any generator's output,
not just this one, to score hallucination rate on the gold event set.
"""

from __future__ import annotations

import dataclasses
import random
import re
from datetime import datetime

from ..events import Event

# Language the system must never use about a person -- these assert guilt
# or intent the structured event never licenses. The system reports
# observations ("an unidentified person entered the restricted area"),
# never verdicts ("this person is a criminal").
DISALLOWED_TERMS = [
    "criminal", "intruder", "suspect", "perpetrator", "thief", "burglar",
    "trespasser", "dangerous person", "armed",
]

IDENTITY_PHRASES_UNKNOWN = ["an unidentified person", "an unknown individual", "an unrecognized person"]
ENTRY_VERBS = ["entered", "walked into", "moved into"]

LOITER_CLAUSES = ["and remained there for {duration}", "and stayed in the area for {duration}"]
ABNORMAL_TRANSITION_CLAUSE = "entering directly without passing through the normal area first"


def format_clock(timestamp_iso: str) -> str:
    dt = datetime.fromisoformat(timestamp_iso)
    hour12 = dt.hour % 12 or 12
    period = "AM" if dt.hour < 12 else "PM"
    return f"{hour12}:{dt.minute:02d} {period}"


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 90:
        return f"approximately {seconds} seconds"
    minutes = seconds // 60
    return f"approximately {minutes} minute{'s' if minutes != 1 else ''}"


@dataclasses.dataclass
class GroundingReport:
    passed: bool
    entity_ok: bool
    numeric_ok: bool
    disallowed_terms_found: list[str]
    notes: list[str]


class EventNarrator:
    """Template-based grounded generator -- the Week 7 baseline in the
    template vs. small-local-model vs. LLM comparison. Deterministic
    given a seed, so output is reproducible for tests and for the
    hallucination-rate evaluation harness.
    """

    def __init__(self, seed: int | None = 7):
        self._rng = random.Random(seed)

    def generate(self, event: Event) -> str:
        time_phrase = format_clock(event.timestamp)
        identity_phrase = (
            self._rng.choice(IDENTITY_PHRASES_UNKNOWN)
            if event.identity in ("unknown", "", None)
            else event.identity
        )
        zone_phrase = f"the {event.zone}" if event.zone else "the monitored area"
        verb = self._rng.choice(ENTRY_VERBS)

        sentence = f"At {time_phrase}, {identity_phrase} {verb} {zone_phrase}"

        clauses = []
        if "loitering" in event.behavior and event.duration_seconds > 0:
            clause_tmpl = self._rng.choice(LOITER_CLAUSES)
            clauses.append(clause_tmpl.format(duration=format_duration(event.duration_seconds)))
        if "abnormal_transition" in event.behavior:
            clauses.append(ABNORMAL_TRANSITION_CLAUSE)

        if clauses:
            sentence += " " + " and ".join(clauses)
        sentence += "."

        if "repeated_entry" in event.behavior:
            sentence += " This location has seen repeated visits from this individual recently."

        if event.risk_level in ("high", "critical"):
            sentence += f" This was flagged as a {event.risk_level}-risk event."

        return sentence

    def generate_summary(self, events: list[Event]) -> str:
        """Grounded multi-event summary for the query engine -- built
        only from the retrieved rows, never from anything outside them.
        """
        if not events:
            return "No matching events were found in the recorded history."
        if len(events) == 1:
            return self.generate(events[0])
        highest = max(events, key=lambda e: e.risk_score)
        zones = sorted({e.zone for e in events if e.zone})
        parts = [f"Found {len(events)} matching events"]
        if zones:
            parts.append(f"across {', '.join(zones)}")
        parts.append(
            f"; the highest-risk was at {format_clock(highest.timestamp)} "
            f"(risk {int(highest.risk_score)}/100, {highest.risk_level})."
        )
        return " ".join(parts)


def check_grounding(narrative: str, event: Event) -> GroundingReport:
    """Slot-based factual-consistency check -- the automatic half of the
    hallucination taxonomy from the project proposal:

      entity hallucination     -> wrong/missing zone or identity
      numeric hallucination    -> a claimed duration that doesn't match
      unsupported inference    -> accusatory language never licensed
                                   by the structured event
      (omission is intentionally not scored here: an incomplete but
      accurate sentence is a fluency problem, not a grounding failure)

    Generator-agnostic by design: run this on template output (should
    always pass) and later on small-LM or LLM output for the Week 7
    comparison.
    """
    notes: list[str] = []
    lower = narrative.lower()

    found_terms = [t for t in DISALLOWED_TERMS if t in lower]
    if found_terms:
        notes.append(f"uses unsupported/accusatory language: {found_terms}")

    entity_ok = True
    if event.zone and event.zone.lower() not in lower:
        entity_ok = False
        notes.append(f"zone '{event.zone}' not mentioned")

    if event.identity in ("unknown", "", None):
        if not re.search(r"unidentified|unknown|unrecognized", lower):
            entity_ok = False
            notes.append("event has unknown identity but narrative doesn't say so")
    elif event.identity.lower() not in lower:
        entity_ok = False
        notes.append(f"identity '{event.identity}' not mentioned")

    numeric_ok = True
    claimed_numbers = [int(n) for n in re.findall(r"\b(\d+)\b", narrative)]
    if "loitering" in event.behavior and claimed_numbers:
        true_seconds = event.duration_seconds
        true_minutes = true_seconds / 60.0
        if not any(
            abs(n - true_seconds) <= max(3, true_seconds * 0.15) or abs(n - true_minutes) <= 1
            for n in claimed_numbers
        ):
            numeric_ok = False
            notes.append(f"claimed duration figure(s) {claimed_numbers} don't match recorded {true_seconds:.0f}s")

    passed = entity_ok and numeric_ok and not found_terms
    return GroundingReport(
        passed=passed,
        entity_ok=entity_ok,
        numeric_ok=numeric_ok,
        disallowed_terms_found=found_terms,
        notes=notes,
    )
