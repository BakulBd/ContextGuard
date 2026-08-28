# Security Policy

ContextGuard processes a live camera feed and stores structured event data locally. It is
a **research / small-deployment** tool, not a hardened enterprise product — please read
the threat-model notes below before deploying it anywhere reachable from a network.

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | ✅ |
| `< 0.1` | ❌ |

This is a pre-1.0 project; security fixes land on `main` and in the next tagged release.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

- Preferred: use GitHub's [private vulnerability reporting](https://github.com/BakulBd/ContextGuard/security/advisories/new)
  ("Report a vulnerability" on the Security tab).
- Or email **cyberbokul@gmail.com** with `ContextGuard security` in the subject.

Please include:

- affected version / commit,
- a description and, ideally, a proof of concept,
- impact (what an attacker gains),
- your environment (OS, Python, install method, dashboard vs. API).

### What to expect

- Acknowledgement within **5 business days**.
- An assessment and a planned fix window within **10 business days** for confirmed issues.
- Credit in the release notes / advisory if you'd like it. This project has no bug-bounty
  budget.

Please give a reasonable window to ship a fix before public disclosure.

## Known limitations by design (not vulnerabilities)

These are documented trade-offs for a local research tool. Reports about them will be
closed with a pointer here:

- **The dashboard password gate is a shared-secret check** (`hmac.compare_digest`), not a
  session/auth system. It exists so a bare `streamlit run` isn't wide open — it is not a
  substitute for TLS or an identity provider.
- **The API key is a single static secret** in `X-API-Key`, with a **loopback-only
  fallback** when no key is set. Rate limiting is in-memory (`slowapi`), not distributed.
- **No TLS is terminated by the app.** Anything beyond `127.0.0.1` must sit behind a
  TLS-terminating reverse proxy (Caddy, nginx, Tailscale). See
  [`deploy/README.md`](deploy/README.md).
- **The API is single-process by design.** Don't run it under `gunicorn -w N`.
- **Model weights are downloaded on first run** from the Ultralytics/PyTorch/Hugging Face
  CDNs. Pre-warm them into your image/host if you need no runtime network egress (the
  `Dockerfile` does this).

## Hardening checklist for real deployments

- [ ] Set `CONTEXTGUARD_DASHBOARD_PASSWORD` and/or `CONTEXTGUARD_API_KEY`.
- [ ] Keep the service bound to `127.0.0.1`; expose it only through a TLS reverse proxy.
- [ ] Run as a non-root user that is in the `video` group (nothing more).
- [ ] Keep `retention_days` as low as your use case allows; keep the purge timer running.
- [ ] Leave `store_thumbnails: false` unless you have a specific need.
- [ ] Keep dependencies current (Dependabot PRs are enabled).
- [ ] Restrict filesystem access to `data/` and the repo directory.
