"""ContextGuard REST API -- the machine-integration surface.

Optional (``pip install -e ".[api]"``): the Streamlit dashboard covers
the single-user local case with no extra dependencies. This package
exists for headless/server deployments and for integrating
ContextGuard's events into another system. See ``api/main.py`` for why
it deliberately runs as a single process/worker.
"""
