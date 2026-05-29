"""Development server for the pyvelm example app.

Usage::

    python examples/serve.py [--host HOST] [--port PORT] [--reload]
    python examples/serve.py --env production --host 0.0.0.0

Requires PYVELM_DSN (copy .env.example to .env). Default mode is
``development``; Docker / gunicorn use ``production``.

Open http://localhost:8000/ (landing) or /login — admin / admin.
Optional: PYVELM_HOME_URL=/ to use the site root as the signed-in home.

Sidebar **Vellum demo** (notes, comments, soft deletes) and **Feedback signals**
(narrative-first feedback analysis) load with this server.

**Date / datetime / time pickers** are on example forms — open any record in
**CRM → All Leads**, **Partners**, **Feedback intakes**, or **Vellum demo → Demo notes**
and click Edit. **Date** uses the Flowbite calendar; **Datetime** opens one popup
(calendar + time); **Time** is a styled time input.

Vellum smoke test (same module roots, no full DB wipe)::

    python examples/vellum_smoke.py

See docs/vellum.md in the repo for the user guide.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.runtime import DEVELOPMENT
from pyvelm.server import apply_runtime_env, default_serve_env, run_dev_server
from pyvelm.web import create_app

load_dotenv(".env")

HERE = Path(__file__).parent
EXAMPLE_ROOT = HERE / "modules"
DEMO_ROOT = HERE / "modules_demo"
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [EXAMPLE_ROOT, DEMO_ROOT]


def _build_app(*, runtime_env: str | None = None):
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set (copy .env.example to .env)")

    env_mode = apply_runtime_env(runtime_env)

    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)
        specs = loader.load_and_install(MODULE_ROOTS, env)
        print("Loaded modules:", [s.name for s in specs])

    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=True)
    app = create_app(
        reg, pool, module_roots=MODULE_ROOTS, runtime_env=env_mode,
    )
    return app


app = _build_app(runtime_env=default_serve_env(from_cli=False))


def main():
    parser = argparse.ArgumentParser(description="pyvelm example server")
    parser.add_argument("--host", default=os.environ.get("PYVELM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PYVELM_PORT", "8000")))
    parser.add_argument(
        "--env",
        choices=[DEVELOPMENT, "production", "dev", "prod"],
        default=None,
        help="Runtime mode (default: development)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on code changes (development only)",
    )
    args = parser.parse_args()

    env_mode = apply_runtime_env(args.env or DEVELOPMENT)

    if args.reload:
        root = str(HERE.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        run_dev_server(
            app="examples.serve:app",
            host=args.host,
            port=args.port,
            runtime_env=env_mode,
            reload=True,
            reload_dirs=[root, str(HERE)],
        )
    else:
        run_dev_server(
            app=_build_app(runtime_env=env_mode),
            host=args.host,
            port=args.port,
            runtime_env=env_mode,
        )


if __name__ == "__main__":
    main()
