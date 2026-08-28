"""Compare narration backends over the current event store, using the
grounding checker (contextguard/nlp/generate.py's check_grounding) as
the automatic factual-consistency metric -- the Week 7 NLP experiment
from the project proposal, operationalized against real recorded
events instead of left as a paper plan.

An external-LLM comparison point is deliberately not wired in here:
per the proposal's own privacy argument, a cloud LLM belongs only in a
separate, explicitly-labeled research harness -- never in code that
runs by default against real recorded events. Add one yourself behind
an equally explicit flag if you need that third data point; don't
default it on.

Usage:
    python tools/compare_narrators.py data/contextguard.db
    python tools/compare_narrators.py data/contextguard.db --limit 50 --with-local-llm
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Callable

from contextguard.events import Event, EventStore
from contextguard.nlp.generate import EventNarrator, check_grounding


def _run_backend(name: str, generate_fn: Callable[[Event], str], events: list[Event]) -> dict:
    latencies: list[float] = []
    passed = 0
    failures: list[tuple[int, str]] = []

    for event in events:
        t0 = time.perf_counter()
        try:
            narrative = generate_fn(event)
        except Exception as exc:  # a broken backend shouldn't abort the whole comparison
            failures.append((event.event_id or -1, f"generation error: {exc}"))
            continue
        latencies.append(time.perf_counter() - t0)

        report = check_grounding(narrative, event)
        if report.passed:
            passed += 1
        else:
            failures.append((event.event_id or -1, "; ".join(report.notes)))

    n = len(events)
    return {
        "backend": name,
        "n": n,
        "grounding_pass_rate": (passed / n) if n else 0.0,
        "mean_latency_ms": statistics.mean(latencies) * 1000 if latencies else 0.0,
        "p95_latency_ms": (sorted(latencies)[int(len(latencies) * 0.95)] * 1000) if latencies else 0.0,
        "failures": failures[:10],  # first 10, for manual read-through -- not a full dump
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("db_path")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--with-local-llm",
        action="store_true",
        help="also evaluate the local small-model backend (slower; needs the 'localllm' extra)",
    )
    args = parser.parse_args()

    store = EventStore(args.db_path)
    events = store.query(limit=args.limit, order="asc")
    if not events:
        print("No events in the store yet -- run the pipeline against some staged scenarios first.")
        return

    backends: list[tuple[str, Callable[[Event], str]]] = [("template", EventNarrator().generate)]
    if args.with_local_llm:
        from contextguard.nlp.local_llm import LocalLLMNarrator

        backends.append(("local_llm", LocalLLMNarrator().generate))

    print(f"Evaluating {len(backends)} backend(s) over {len(events)} events.\n")
    results = [_run_backend(name, fn, events) for name, fn in backends]

    header = f"{'backend':<12}{'n':>6}{'grounding pass %':>18}{'mean ms':>10}{'p95 ms':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['backend']:<12}{r['n']:>6}{r['grounding_pass_rate'] * 100:>17.1f}%"
            f"{r['mean_latency_ms']:>10.1f}{r['p95_latency_ms']:>10.1f}"
        )

    for r in results:
        if r["failures"]:
            print(f"\n{r['backend']} -- sample grounding failures (event_id: reason):")
            for event_id, reason in r["failures"]:
                print(f"  #{event_id}: {reason}")


if __name__ == "__main__":
    main()
