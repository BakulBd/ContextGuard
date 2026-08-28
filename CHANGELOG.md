# Changelog

All notable changes to ContextGuard are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Project documentation set: `LICENSE` (MIT + third-party notes), `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CITATION.cff`, this changelog, GitHub issue/PR
  templates, and Dependabot configuration.
- Packaging metadata in `pyproject.toml`: license, authors, keywords, classifiers, and
  project URLs.

## [0.1.0] - 2026-08-28

Initial release — the full Week 1–9 core pipeline, verified end to end against a real
webcam and a real API server.

### Added
- **Capture & tracking** — `CameraSource` abstraction over webcam index / USB / `rtsp://`
  with auto-reconnect and backoff; YOLO26n detection and ByteTrack tracking via
  Ultralytics.
- **Zones & context** — rectangle zone editor (dashboard) and arbitrary-polygon zones
  (API); per-track dwell time, loitering, repeat visits, after-hours and abnormal-zone-
  transition detection; dependency-free point-in-polygon (`geometry.py`).
- **Risk engine** — Approach A (transparent point rules, live default), Approach B
  (rule shape with weights derived from a trained model), Approach C (logistic
  regression), plus three naive baselines. Shared feature set and explainable
  `RiskResult` breakdown. `create_risk_engine()` falls back to Approach A when trained
  artifacts are absent.
- **Event store** — SQLite persistence with `retention_days` enforced by
  `tools/purge_old_events.py`.
- **Grounded NLG** — deterministic template narrator with a `check_grounding()`
  hallucination checker; opt-in small local-model backend (`SmolLM2-360M-Instruct`, no
  inference-time network).
- **Natural-language queries** — intent/slot parsing → SQL filter → grounded answer,
  in the dashboard and via `POST /query`.
- **Streamlit dashboard** — live annotated feed, zone editor, event log, timeline, NL
  query tab, performance panel; optional password gate; pinned to `127.0.0.1`.
- **REST API** (opt-in `[api]`) — `events`, `zones`, `query`, `frame.jpg`,
  `stream.mjpg`, `healthz`, `readyz`, Prometheus `metrics`; `X-API-Key` auth with
  loopback fallback; in-memory rate limiting.
- **Alerts** — on-screen annotations and desktop notifications with per-track cooldown
  and a minimum-level threshold.
- **Ops** — rotating file + console logging, per-frame/per-track fault isolation, env-var
  overrides for every config field, `Dockerfile` + `docker-compose.yml`, systemd units
  and `scripts/serve.sh`.
- **Tooling** — `benchmark_detector.py` (with `--compare`), `train_risk_model.py`,
  `purge_old_events.py`, `compare_narrators.py`.
- **Tests & CI** — 81 unit tests (no camera or model download required), including the
  full REST API via a fake injected service; GitHub Actions running pytest on Python
  3.11 / 3.12 / 3.14 plus a Docker build.

### Known gaps (deliberate)
- Identity enrollment / Re-ID is not implemented — `contextguard/identity.py` is a
  documented seam; the system always runs anonymous.
- No external-LLM narration comparison is wired into the default path.
- Docker images are not build-tested (no Docker in the build sandbox).

[Unreleased]: https://github.com/BakulBd/ContextGuard/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BakulBd/ContextGuard/releases/tag/v0.1.0
