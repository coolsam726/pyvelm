"""``pyvelm serve`` — run the FastAPI dev/prod server (uvicorn)."""

from __future__ import annotations

from pyvelm.console import Command
from pyvelm.runtime import DEVELOPMENT
from pyvelm.scaffolder import find_project_root
from pyvelm.server import (
    apply_runtime_env,
    build_serve_app,
    guess_serve_import,
    prepare_reload_import,
    run_dev_server,
)


class ServeCommand(Command):
    name = "serve"
    description = "Run the FastAPI app with uvicorn (development or production)"
    signature = (
        "serve "
        "{--host=127.0.0.1 : Bind address} "
        "{--port=8000 : TCP port} "
        "{--env=development : Runtime mode (development, production, dev, prod)} "
        "{--reload : Auto-reload on code changes (development only)} "
        "{--app= : ASGI import string for --reload (e.g. app.serve:app)}"
    )

    def handle(
        self,
        host: str = "127.0.0.1",
        port: str = "8000",
        env: str = DEVELOPMENT,
        reload: bool = False,
        app: str | None = None,
    ) -> int:
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            self.error(f"Invalid port {port!r}.")
            return 1

        env_mode = apply_runtime_env(env or DEVELOPMENT)
        roots = self._ctx.roots
        project_root = find_project_root()

        if reload:
            import_str = (app or "").strip() or guess_serve_import(
                project_root=project_root,
            )
            if not import_str:
                self.error(
                    "Could not guess an ASGI import string. "
                    "Pass --app=app.serve:app (or examples.serve:app)."
                )
                return 1
            reload_dirs = prepare_reload_import(import_str)
            run_dev_server(
                app=import_str,
                host=host,
                port=port_i,
                runtime_env=env_mode,
                reload=True,
                reload_dirs=reload_dirs,
            )
            return 0

        asgi_app = build_serve_app(roots, runtime_env=env_mode)
        run_dev_server(
            app=asgi_app,
            host=host,
            port=port_i,
            runtime_env=env_mode,
        )
        return 0
