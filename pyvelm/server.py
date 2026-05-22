"""ASGI dev-server helpers shared by ``app.serve`` and ``examples.serve``."""
from __future__ import annotations

import os
import sys
from typing import Any

from .runtime import DEVELOPMENT, PRODUCTION, get_runtime_env, is_development


def run_dev_server(
    *,
    app: Any | str,
    host: str = "127.0.0.1",
    port: int = 8000,
    runtime_env: str | None = None,
    reload: bool = False,
    reload_dirs: list[str] | None = None,
) -> None:
    """Run uvicorn with settings appropriate for dev or production mode.

    ``app`` is either the FastAPI instance or an import string (required
    when ``reload=True``).
    """
    import uvicorn

    env = get_runtime_env(runtime_env)
    dev = is_development(env)
    if reload and not dev:
        print("warning: --reload is ignored in production mode", file=sys.stderr)
        reload = False

    log_level = "debug" if dev else "info"
    mode_label = "development" if dev else "production"

    print(f"\nPYVELM_ENV={env} ({mode_label})")
    print(f"Serving at http://{host}:{port}/login")
    if dev:
        print("API docs: http://{0}:{1}/docs".format(host, port))
    print("Default credentials: admin / admin\n")

    kwargs: dict = {
        "host": host,
        "port": port,
        "log_level": log_level,
    }
    if reload:
        if isinstance(app, str):
            target = app
        else:
            raise ValueError("reload requires app as an import string")
        kwargs["reload"] = True
        if reload_dirs:
            kwargs["reload_dirs"] = reload_dirs
        uvicorn.run(target, **kwargs)
    else:
        uvicorn.run(app, **kwargs)


def apply_runtime_env(runtime_env: str | None) -> str:
    """Set ``PYVELM_ENV`` in ``os.environ`` when an explicit mode is passed."""
    if runtime_env is None:
        return get_runtime_env()
    env = get_runtime_env(runtime_env)
    os.environ["PYVELM_ENV"] = env
    return env


def default_serve_env(*, from_cli: bool) -> str:
    """Default mode for ``python -m …serve`` vs gunicorn import."""
    if os.environ.get("PYVELM_ENV"):
        return get_runtime_env()
    return DEVELOPMENT if from_cli else PRODUCTION
