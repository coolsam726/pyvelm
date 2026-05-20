"""Gunicorn configuration for the pyvelm dev / small-production deploy.

Notes for operators
-------------------

- **Workers.** Default to 2 × CPU + 1, which is the conventional
  starting point for I/O-bound ASGI workloads. Tune via the
  ``GUNICORN_WORKERS`` env var.
- **Worker class.** ``UvicornWorker`` runs the FastAPI app on uvicorn's
  asyncio loop, which is what the framework's request handlers expect.
- **In-memory state is per-worker.** The ``/login`` rate limiter and
  the connection-pool object live in process memory, so:

  * Each worker enforces its own 5-attempts-per-window count — N
    workers ≈ 5N effective attempts.  For real production put a
    proper rate limit on the reverse proxy (nginx ``limit_req``,
    Cloudflare, etc.) and treat the per-worker limit as a backstop.
  * ``psycopg_pool.ConnectionPool`` opens its own pool per worker —
    set Postgres's ``max_connections`` to at least
    ``workers × pool_max_size`` plus headroom.

- **Trusted proxies.** When you run behind a reverse proxy, set
  ``forwarded_allow_ips`` to the proxy's IP so ``request.client.host``
  reflects the real client (used by the login rate limiter).
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
# Keepalive: long enough that browser-bound clients reuse connections,
# short enough not to tie up workers behind a slow client.
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", 5))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", 30))
# Trust the proxy's X-Forwarded-* headers when listed here. Wildcard
# only when explicitly enabled — accepting it from anywhere lets a
# direct caller spoof their IP.
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")

# Tee the stdout/stderr logs to docker.
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
