# ContextGuard API service image. See api/main.py for why this runs as
# a single process (one camera, one in-process pipeline -- no
# multi-worker gunicorn here).
#
# Webcam passthrough only works reliably on a Linux Docker host
# (`--device /dev/video0`, see docker-compose.yml). Docker Desktop on
# macOS/Windows cannot pass a USB webcam through to a Linux container;
# on those platforms either run natively (see the main README) or
# point CONTEXTGUARD_CAMERA_SOURCE at an rtsp:// source the container
# can reach over the network instead of a local device.
#
# This intentionally packages the API service, not the Streamlit
# dashboard -- the dashboard is the simple local-single-user path and
# doesn't need containerizing; this image is for the "run it on a
# headless box, integrate it with something else" deployment shape.

FROM python:3.14-slim AS base

# OpenCV's runtime needs these even for headless/no-GUI use.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch, installed first and separately: the default PyPI
# torch wheel drags in several GB of CUDA libraries this CPU-only image
# will never use (see README.md's Setup section for the same reasoning
# applied to a local install).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY contextguard ./contextguard
COPY api ./api
RUN pip install --no-cache-dir -e ".[api]"

# Pre-warm model weights into the image so the container has no
# first-request latency spike and needs no network egress after startup.
RUN python -c "from ultralytics import YOLO; YOLO('yolo26n.pt')"

RUN useradd --create-home --uid 1000 contextguard \
    && mkdir -p /app/data && chown -R contextguard:contextguard /app
USER contextguard

ENV CONTEXTGUARD_CAMERA_SOURCE=0 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
