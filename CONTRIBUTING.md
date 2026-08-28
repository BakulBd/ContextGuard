# Contributing to ContextGuard

Thanks for your interest. ContextGuard is a small, honest research/deployment tool, and
contributions that keep it that way are very welcome.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

- **Open an issue first** for anything non-trivial (a feature, a behaviour change, a new
  dependency). Small bug fixes and docs can go straight to a PR.
- **"Verified, not assumed."** This project's README documents which claims were checked
  against a real run. Hold your contributions to the same bar: if you say something
  works, say *how you checked*. Don't add aspirational text.
- **No new default cloud calls.** A cloud LLM or any remote inference belongs only in an
  explicit, opt-in research harness — never in a path that runs by default against
  recorded events. PRs that change this will be declined.
- **Privacy stays the default.** Anonymous tracking, no stored thumbnails, enforced
  retention. New features must not quietly weaken any of these.
- **Match the surrounding code** — its naming, its structure, and its comment density
  (this codebase comments the *why*, generously; keep that up).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only, first
pip install -e ".[dev,api,localllm]"
```

See the [README](README.md#installation) for why torch is installed separately and for
the `uv` alternative.

## Running the checks

```bash
pytest                    # 81 tests; no camera or model download required
python -c "import ast; ast.parse(open('dashboard/app.py').read())"          # dashboard import-check
python -c "import tools.benchmark_detector, tools.train_risk_model, \
           tools.purge_old_events, tools.compare_narrators, api.main"       # tools + API import-check
```

CI runs exactly this on Python 3.11 / 3.12 / 3.14 plus a Docker build. Camera-touching
code (`contextguard/camera.py`, `scripts/run_headless.py`) is **not** covered by CI —
exercise it by hand on real hardware and describe what you did in the PR.

### Tests for new behaviour

Anything that doesn't need a camera or a model download should be unit-tested. The REST
API is tested through a fake injected pipeline service — see `api/state.py`'s
`set_service` seam and `tests/test_api.py` for the pattern.

## Pull request checklist

- [ ] Linked to an issue (for non-trivial changes)
- [ ] `pytest` passes locally
- [ ] New/changed behaviour has tests
- [ ] Docs updated (README table, `CHANGELOG.md` under `[Unreleased]`, docstrings)
- [ ] No new default network calls; privacy defaults intact
- [ ] Camera/hardware paths tested by hand, with a note on how
- [ ] Commit messages are imperative and explain the *why*

## Commit and branch conventions

- Branch from `main`; name branches like `fix/camera-reconnect-backoff` or
  `feat/polygon-zone-editor`.
- Write imperative commit subjects (`Add …`, `Fix …`, not `Added` / `Fixes`). A short
  body explaining the reasoning is appreciated.
- There is no CLA. Standard inbound-equals-outbound: your contribution is licensed under
  the repository's [MIT License](LICENSE).

## Reporting bugs

Use the bug report issue template. Include your OS, Python version, how you installed
(`uv` / `pip` / Docker), the camera source, the full traceback, and the relevant lines
from `data/logs/contextguard.log`.

## Security issues

Do **not** file them as public issues — see [SECURITY.md](SECURITY.md).
