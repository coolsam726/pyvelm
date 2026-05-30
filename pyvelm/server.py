"""ASGI dev-server helpers shared by ``app.serve``, ``examples.serve``, and ``pyvelm serve``."""
from __future__ import annotations

import os
import sys
from pathlib import Path
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


def guess_serve_import(*, project_root: Path | None = None) -> str | None:
    """Best-effort ASGI import string for ``pyvelm serve --reload``."""
    root = (project_root or Path.cwd()).resolve()
    if (root / "app" / "serve.py").is_file():
        return "app.serve:app"
    if (root / "examples" / "serve.py").is_file():
        return "examples.serve:app"
    return None


def prepare_reload_import(import_str: str) -> list[str]:
    """Put the project on ``sys.path`` and return uvicorn ``reload_dirs``."""
    from .scaffolder import find_project_root

    root = find_project_root() or Path.cwd().resolve()
    if import_str.startswith("app.serve:"):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return [str(root), str(root / "app")]
    if import_str.startswith("examples.serve:"):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return [str(root), str(root / "examples")]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return [str(root)]


def build_serve_app(
    module_roots: list[Path | str],
    *,
    runtime_env: str | None = None,
) -> Any:
    """Load modules from the DB and return a FastAPI app for ``pyvelm serve``."""
    import psycopg
    from dotenv import find_dotenv, load_dotenv
    from psycopg_pool import ConnectionPool

    from . import Environment, Registry, loader
    from .web import create_app

    load_dotenv(find_dotenv(usecwd=True))
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set (copy .env.example to .env)")

    env_mode = apply_runtime_env(runtime_env)

    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)
        specs = loader.load_and_install(module_roots, env)
        print("Loaded modules:", [s.name for s in specs])

    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=True)
    return create_app(
        reg, pool, module_roots=module_roots, runtime_env=env_mode,
    )
