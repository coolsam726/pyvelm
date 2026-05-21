"""Development server for the pyvelm example app.

Loads the example modules, installs/upgrades them, then serves the
FastAPI app with uvicorn so you can explore the UI in a browser.

Usage:
    python examples/serve.py [--host HOST] [--port PORT] [--reload]

Requires PYVELM_DSN to be set (copy .env.example to .env).

Tip: open http://localhost:8000/login and sign in as admin / admin.
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
from pyvelm.web import create_app

load_dotenv(".env")

HERE = Path(__file__).parent
# Three discovery roots:
#   - BUILTIN_MODULE_ROOTS (inside the pyvelm wheel) ships `base` +
#     `admin` — the framework primitives and their management UI.
#   - `examples/modules/` is the illustrative addons set: partners,
#     partners_pro, crm. These show off patterns rather than being
#     required by the framework.
#   - `examples/modules_demo/` carries the optional `demo` module
#     whose install hook seeds ~20 partners + 15 leads so the UI is
#     populated for live testing.
EXAMPLE_ROOT = HERE / "modules"
DEMO_ROOT = HERE / "modules_demo"
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [EXAMPLE_ROOT, DEMO_ROOT]


def _build_app():
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set (copy .env.example to .env)")

    # Install / upgrade modules using a one-shot autocommit connection,
    # then hand off to the pool-backed ASGI app. load_and_install is
    # idempotent — re-running serve.py picks up version bumps but
    # leaves any data the demo hook already seeded alone.
    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)
        specs = loader.load_and_install(MODULE_ROOTS, env)
        print("Loaded modules:", [s.name for s in specs])

    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=True)
    # `module_roots` powers the /web/apps catalog — it needs to know
    # where to look for manifests when listing available / installable
    # modules, not just what's already in `ir_module`.
    return create_app(reg, pool, module_roots=MODULE_ROOTS)


# Module-level `app` so uvicorn --reload can import it.
app = _build_app()


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="pyvelm dev server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (development only)",
    )
    args = parser.parse_args()

    print(f"\nServing at http://{args.host}:{args.port}/login")
    print("Default credentials: admin / admin\n")

    if args.reload:
        # Reload mode requires an importable string. Add the project root
        # to PYTHONPATH so `examples.serve` resolves correctly.
        import sys
        root = str(Path(__file__).parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        uvicorn.run(
            "examples.serve:app",
            host=args.host,
            port=args.port,
            reload=True,
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
