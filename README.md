# ContextGuard

Privacy-preserving, context-aware intrusion reasoning and grounded
natural-language security intelligence for a laptop webcam — no GPU,
no mandatory cloud, no continuous video retention by default.

Full project proposal (literature review, research questions,
evaluation plan, and an honest critique of what is and isn't a real
contribution here): **[ContextGuard proposal](https://claude.ai/code/artifact/26c9b407-f7d5-4baa-a7cb-872fc44dc4b4)**.

[![CI](https://github.com/OWNER/ContextGuard/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/ContextGuard/actions/workflows/ci.yml)
*(replace `OWNER` once this is pushed to a GitHub remote)*

```
webcam -> detect (YOLO26n) -> track (ByteTrack) -> zones -> duration/loitering
       -> risk engine (rule / weighted / logistic regression)
       -> event store (SQLite) -> grounded narrative -> alert
       -> Streamlit dashboard  -or-  REST API (api/) for integration
```

## Status

The full Week 1–9 core pipeline from the proposal, working end to end
and verified against a real webcam and a real API server while this
was built (not just reasoned through) — see *Verified, not assumed*
below. What's real vs. what's an intentionally unbuilt seam:

| Piece | Status |
|---|---|
| Camera abstraction, YOLO26n detection, ByteTrack tracking | implemented |
| Zone drawing (rectangles, via the dashboard or the API), entry/exit/dwell/loitering/repeat-visit | implemented |
| Risk engine — Approach A (rule), baselines 1–3 | implemented, live default |
| Risk engine — Approach B (weights derived from a trained model) | implemented; needs `tools/train_risk_model.py` run on your own labeled data first |
| Risk engine — Approach C (logistic regression) | implemented; same data dependency as B |
| Event store, retention/purge | implemented |
| Grounded template narrative generation + hallucination checker | implemented |
| Small local-model narration backend (`nlp/local_llm.py`) | implemented, opt-in (`.[localllm]`); `tools/compare_narrators.py` runs the template-vs-local-model comparison the proposal calls for, scored by the grounding checker |
| Natural-language query engine (intent/slot → SQL filter → grounded answer) | implemented |
| Streamlit dashboard: live feed, zones, events, timeline, NL query, performance panel | implemented, password-gated |
| REST API (`api/`): events/zones/query/live-frame/health/Prometheus metrics, API-key auth, rate limiting | implemented, opt-in (`.[api]`) |
| Local desktop alerts | implemented |
| Docker image + systemd units for standing deployment | implemented |
| Identity enrollment / Re-ID (Mode 1) | **not implemented** — deliberately deferred, see `contextguard/identity.py`. The system always runs in anonymous mode (temporary track IDs only), which the proposal argues should be the default anyway. |
| External-LLM narration comparison point | **not wired in** — deliberately: per the proposal's privacy argument, a cloud LLM belongs only in an explicit, separate research harness, never in code that runs by default against real recorded events. |

### Verified, not assumed

Every claim below was checked against a real run while this was built,
not just written and hoped for:

- YOLO26n loads, downloads its weights (5.3 MB), and runs inference on
  this dev machine's CPU at **~24 FPS** synthetic / **~23 FPS** live
  camera, comfortably over the ≥10 FPS target — via
  `tools/benchmark_detector.py --source synthetic` and a live end-to-end
  run against `/dev/video0`.
- The full pipeline (`ContextGuardPipeline`) runs against a real
  webcam frame-by-frame with no crashes.
- The real (non-test-double) API service boots, opens the camera,
  serves `/healthz`, `/events`, `/zones`, `/metrics`, and a live
  `/frame.jpg` JPEG snapshot, and correctly returns 401 without an API
  key and 200 with one.
- The Streamlit dashboard, run with zero flags, was confirmed via
  `ss -tlnp` to bind to `127.0.0.1` only — not Streamlit's actual
  out-of-the-box default (see `.streamlit/config.toml`'s comment for
  what that default really is and how this was caught).
- All 81 automated tests pass on Python 3.14.

## Requirements

- A laptop with a webcam. No discrete GPU required — everything here
  runs on CPU.
- Python 3.10+. Developed and tested against 3.14, where a few
  proposal-suggested dependencies don't have wheels yet and were
  swapped out accordingly: `onnxruntime` (no 3.14 build → the pipeline
  uses Ultralytics' PyTorch backend directly instead of an ONNX
  export) and `shapely` (no 3.14 wheel, needs a system GEOS to build →
  `contextguard/geometry.py` implements point-in-polygon by hand, ~40
  dependency-free lines). If you're on an older Python, both would
  work fine too; the custom geometry code is simpler either way and
  was kept regardless.

## Setup

`ultralytics` pulls in `torch`, and torch's default PyPI wheel bundles
the full CUDA/cuDNN/NCCL stack -- several GB -- even on a machine with
no GPU, which is exactly what this project doesn't need. Two ways to
avoid downloading that for nothing:

**Recommended — [uv](https://docs.astral.sh/uv/)** (also just faster;
plain pip's resolver can spend a long time backtracking on this
dependency set, and in one build of this project a single giant
`uv pip install` transaction itself stalled on a slow connection --
installing in a couple of stages, as below, was both faster and more
resilient to a flaky network):

```bash
python3 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install uv
uv pip install -e .              # small deps first
uv pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch, isolated
uv pip install opencv-python ultralytics lap                             # detector + tracker
```

(`uv pip install -e ".[dev]"` in one shot also works and is what
`pyproject.toml`'s `[tool.uv.sources]` CPU-index pin is there for —
the staged version above is only worth it if your connection is slow
enough that one giant transaction is a risk.)

**Plain pip** (`pyproject.toml`'s CPU-index pin only applies to `uv`
— install the CPU build explicitly first so pip doesn't reach for the
CUDA one):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
```

**Optional extras:**

```bash
pip install -e ".[api]"        # REST API service (api/) -- FastAPI, uvicorn, slowapi, prometheus-client
pip install -e ".[localllm]"   # small local-model narration backend -- transformers, accelerate
pip install -e ".[dev,api,localllm]"   # everything
```

The first run downloads `yolo26n.pt` (~5 MB) automatically via
Ultralytics.

## Quickstart

**1. Sanity-check the pipeline against your real webcam** (fastest way
to confirm detection/tracking/zones work before touching the
dashboard):

```bash
python scripts/run_headless.py       # press 'q' to quit
```

**2. Benchmark the detector on your machine** — published FPS numbers,
including the YOLO26n-vs-YOLOv8n figures this project's default is
based on, are measured on specific hardware and shouldn't be trusted
as-is for a different laptop:

```bash
python tools/benchmark_detector.py --source 0 --frames 150
python tools/benchmark_detector.py --compare      # yolo26n vs yolov8n, back to back
```

**3. Run the dashboard:**

```bash
streamlit run dashboard/app.py
```

In the sidebar: set the camera source (default `0`), press **📷
Capture frame** under **Zones** to grab a snapshot, drag a rectangle
over the area you want protected, name it, mark it `restricted` or
`normal`, and save. Press **▶ Start** to begin monitoring. Ask
questions in the **Ask ContextGuard** tab, e.g. *"What happened in the
last 30 minutes?"* or *"Which zone had the most incidents?"*

**3b. Or run the REST API instead** (for headless/server use, or to
integrate ContextGuard's events into another system — see
[api/main.py](api/main.py) for why you run this *or* the dashboard,
not both, against one camera):

```bash
pip install -e ".[api]"
uvicorn api.main:app --host 127.0.0.1 --port 8000
# interactive docs: http://127.0.0.1:8000/docs
```

## Training the risk model (Approaches B and C)

Both need real labeled data — they're not meaningful trained on a
handful of clicks:

```bash
# after collecting some staged scenarios with the pipeline running:
python tools/train_risk_model.py export data/contextguard.db data/labeling_template.csv
# open the CSV, fill in `should_alert` (0/1) for each row by hand
python tools/train_risk_model.py train data/labeling_template.csv
# then set risk_mode: weighted (or ml) in config.yaml
```

## Comparing narration backends

```bash
pip install -e ".[localllm]"   # first time only -- downloads SmolLM2-360M-Instruct on first use
python tools/compare_narrators.py data/contextguard.db --with-local-llm
```

Reports grounding-check pass rate and latency for the template
generator vs. the small local model, side by side, over your actual
recorded events — the automatic half of the Week 7 NLP experiment from
the proposal.

## Tests

Everything that doesn't need a camera or a downloaded model — geometry,
zones, the context/duration state machine, all three risk engines, the
event store, the grounded narrator and its hallucination checker, the
NL query engine, the local-LLM prompt builder, and the full REST API
(via a fake injected pipeline service, see `api/state.py`'s
`set_service`) — is unit-tested:

```bash
pytest          # 81 tests, no camera or model download required
```

## Production deployment

Running this as a standing service (survives reboots, restarts on
crash, enforces retention automatically, gated behind a password/API
key once it's reachable beyond your own machine) is covered in
**[deploy/README.md](deploy/README.md)** — systemd units for Linux, a
restart-loop shell script (`scripts/serve.sh`) for everything else, and
a `Dockerfile`/`docker-compose.yml` for the API service.

Production-relevant pieces already built into the app itself, not
bolted on separately:

- **Logging**: every module logs through `contextguard/logging_setup.py`
  to both the console and a rotating file at `data/logs/contextguard.log`
  (5 MB × 5 backups). Set `CONTEXTGUARD_LOG_LEVEL=DEBUG` for more detail.
- **Camera resilience**: `CameraSource` auto-reconnects with backoff
  after repeated read failures (device unplugged, laptop sleep/wake) —
  a long-running deployment shouldn't need someone to notice and
  restart the process by hand.
- **Frame-level fault isolation**: `ContextGuardPipeline.step()` catches
  and logs exceptions per-frame and per-track rather than letting one
  bad frame crash an unattended service.
- **Config via environment**: any `config.yaml` field can be overridden
  with `CONTEXTGUARD_<FIELD_NAME>` (e.g. `CONTEXTGUARD_RISK_MODE=weighted`)
  — see `.env.example`. Useful for systemd `EnvironmentFile=` or a
  container without hand-editing YAML on every deploy.
- **Dashboard auth**: setting `CONTEXTGUARD_DASHBOARD_PASSWORD` gates
  the whole dashboard behind a password screen (`hmac.compare_digest`,
  not a real session/auth system — pair with a reverse proxy and TLS
  for anything beyond localhost).
- **API auth + rate limiting**: the REST API requires `X-API-Key`
  (`CONTEXTGUARD_API_KEY`) for every route except `/healthz`/`/readyz`,
  falling back to loopback-only when no key is configured (same
  philosophy as the dashboard). Rate-limited in-memory via `slowapi`
  (120/min default, 20/min on `/query`) — intentionally not
  Redis-backed, because this service is single-process by hardware
  necessity (see `api/main.py`) and there's never a second process to
  share limiter state with.
- **Binds to localhost only, verified, not assumed**: Streamlit's own
  default (`server.address` unset) is to listen on *all* interfaces —
  confirmed against a running instance while building this project,
  where it printed a LAN "Network URL" and a WAN "External URL" with
  no flags passed at all. `.streamlit/config.toml` pins
  `server.address = "127.0.0.1"` at the project level so a bare
  `streamlit run dashboard/app.py` is safe by default; re-verified with
  `ss -tlnp` afterwards to confirm the socket actually only listens on
  loopback. The API's Dockerfile binds `0.0.0.0` *inside* the
  container, which is normal — the real boundary is the host port
  mapping in `docker-compose.yml` (`127.0.0.1:8000:8000`, not `8000:8000`).
- **Retention enforcement**: `tools/purge_old_events.py`, meant to run
  on a daily timer (see `deploy/`), actually deletes events past
  `retention_days` instead of that config value being aspirational.
- **Observability**: `/metrics` (Prometheus format — FPS, CPU, RAM,
  frames processed, event count) alongside `/healthz` (liveness) and
  `/readyz` (readiness, distinct from liveness: the capture thread can
  be alive while still waiting on its first camera read).
- **Explicit dependency pinning over implicit runtime installs**:
  `lap` (ByteTrack's assignment solver) is pinned in `pyproject.toml`
  rather than left to Ultralytics' auto-install-on-first-use — caught
  by actually running the tracker end to end, where it silently
  pip-installed a package mid-run.
- **CI**: `.github/workflows/ci.yml` runs the full test suite (CPU-only
  torch, same reasoning as local Setup) on Python 3.11 / 3.12 / 3.14,
  plus a Docker build-only job, on every push and PR.

## Project layout

```
contextguard/            # all real logic; camera/tracking swapped, everything else stays put
  camera.py               # webcam / USB / rtsp:// abstraction (index 0 required, rest optional), auto-reconnect
  tracking.py              # YOLO26n detection + ByteTrack (via Ultralytics' built-in tracker)
  geometry.py               # dependency-free point-in-polygon
  zones.py                   # zone CRUD + persistence (data/zones.json)
  context.py                  # per-track dwell time, loitering, repeat visits, after-hours
  risk.py                      # Approaches A/B/C + the 3 naive baselines they're compared against
  events.py                     # SQLite event store
  alerts.py                      # on-screen + local desktop notification, with cooldown
  identity.py                     # Mode 1 seam -- not implemented, see Status above
  perf.py                          # FPS / CPU / RAM, shared by the dashboard, API, and benchmark script
  logging_setup.py                  # rotating file + console logging, used by every module
  pipeline.py                        # wires all of the above into one per-frame step()
  nlp/
    generate.py                     # grounded template narration + check_grounding() hallucination checker
    local_llm.py                     # small local-model narration backend, same generate(event) interface
    query.py                         # intent/slot parsing -> SQL filter -> grounded answer
api/                       # REST API (optional, `.[api]`) -- see api/main.py for the single-process rationale
  main.py                   # FastAPI app, lifespan-managed capture thread
  state.py                   # the one running pipeline + latest frame, shared across requests
  security.py                 # API-key auth (loopback fallback) + rate limiting
  schemas.py                   # Pydantic request/response models
  routes/                       # health, events, zones, query, stream (MJPEG/JPEG), metrics (Prometheus)
dashboard/app.py          # Streamlit UI (thin -- presentation only), password-gated
.streamlit/config.toml    # pins the dashboard to 127.0.0.1 -- see Production deployment
scripts/
  run_headless.py          # cv2.imshow sanity check, no Streamlit
  serve.sh                  # production entrypoint w/ restart-on-crash (non-systemd hosts)
tools/
  benchmark_detector.py    # FPS/latency/memory on this machine, with a --compare mode
  train_risk_model.py       # label export + Approach B/C training
  purge_old_events.py        # retention enforcement, meant to run on a schedule
  compare_narrators.py        # template vs. local-LLM grounding-pass-rate comparison
deploy/                    # systemd units + deployment instructions
Dockerfile, docker-compose.yml, .dockerignore   # containerized API service
.github/workflows/ci.yml   # pytest (3.11/3.12/3.14) + Docker build, on every push/PR
tests/                     # pytest, no camera or model download required (81 tests)
```

## Known rough edges

- **The dashboard's live feed** uses Streamlit's standard pattern for
  this (process one frame per script run, then `st.rerun()`) — it
  works, but a WebSocket-based front end (`streamlit-webrtc`, or the
  React dashboard mentioned as a stretch goal in the proposal) would
  be smoother. The REST API's `/stream.mjpg` is a lower-latency
  alternative if you're building a custom front end. Good next step
  once the core pipeline is validated on your hardware.
- **Zone drawing supports rectangles only** (not arbitrary polygons)
  — `streamlit-drawable-canvas`'s polygon mode encodes vertices as an
  SVG path rather than a plain point list, which wasn't worth the
  fragility to parse blind without a browser to verify against.
  Rectangles satisfy the brief and cover the common case (a room, a
  server rack, a doorway). The REST API's `POST /zones` accepts any
  polygon programmatically, if you have another way to produce one.
- **Camera permissions on Linux**: if `scripts/run_headless.py` can't
  open the camera, confirm your user is in the `video` group and no
  other application (browser tab, video call) is holding the device.
- **The API service is single-process by design** (see `api/main.py`)
  — don't run it under `gunicorn -w N`; each worker would fight over
  the one camera device. Scale reads (not capture) with a cache in
  front of `/events`/`/stream.mjpg` if you need to.
