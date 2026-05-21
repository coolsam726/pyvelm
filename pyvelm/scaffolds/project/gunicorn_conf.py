"""Gunicorn configuration for the {{name}} app.

Defaults match pyvelm's recommended baseline. Tune via env vars:

    GUNICORN_BIND             default 0.0.0.0:8000
    GUNICORN_WORKERS          default 2*CPU+1 (1 if you don't
                              also run a proxy-side rate limiter —
                              the /login rate limit is per-worker)
    GUNICORN_TIMEOUT          default 30
    GUNICORN_FORWARDED_ALLOW_IPS    default 127.0.0.1

Behind a reverse proxy, set GUNICORN_FORWARDED_ALLOW_IPS to the
proxy's IP / CIDR so request.client.host sees the real client.
"""
from __future__ import annotations

import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(
    os.environ.get(
        "GUNICORN_WORKERS",
        max(2, multiprocessing.cpu_count() * 2 + 1),
    )
)
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", 5))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", 30))
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")

accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
