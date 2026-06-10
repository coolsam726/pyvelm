"""On-demand geography seed — ``POST /web/geo-data/seed``."""
from __future__ import annotations

import json
import logging
import threading
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from pyvelm import Environment
from pyvelm.request_env import apply_request_scope

log = logging.getLogger("pyvelm.geo_data")


def register_routes(app) -> None:
    registry = app.state.registry
    pool = app.state.pool

    def _resolve_session(env, token):
        from pyvelm.session_auth import resolve_session_uid

        return resolve_session_uid(env, token)

    def get_env(request: Request):
        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env = apply_request_scope(
                env, request, resolve_session=_resolve_session
            )
            yield env

    def _run_full_seed() -> None:
        try:
            from geo_data.seeders.geography import GeographyDatabaseSeeder

            with pool.connection() as conn:
                bg_env = Environment(conn, registry=registry, uid=1)
                with bg_env.transaction():
                    counts = GeographyDatabaseSeeder.run(
                        bg_env,
                        force=True,
                        patch_existing=True,
                        geo_seed_level="full",
                    )
            log.info("geo_data: background geography seed finished: %s", counts)
        except Exception:  # noqa: BLE001
            log.exception("geo_data: background geography seed failed")

    @app.post("/web/geo-data/seed")
    def seed_geography(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if env.uid != 1:
            raise HTTPException(
                status_code=403,
                detail="Seeding geography data requires superuser (uid=1)",
            )
        if "res.country" not in env.registry:
            raise HTTPException(status_code=404, detail="geo_data is not installed")

        from pyvelm.geo_utils import geo_packages_available

        if not geo_packages_available():
            raise HTTPException(
                status_code=400,
                detail="geo_data needs the geo extras: pip install pyvelm[geo]",
            )

        threading.Thread(target=_run_full_seed, daemon=True).start()

        summary = (
            "Full geography import started in the background "
            "(countries, states, cities). Refresh this list in a minute."
        )
        if request.headers.get("HX-Request"):
            return Response(
                status_code=200,
                headers={
                    "HX-Trigger": json.dumps(
                        {
                            "pv-toast": {
                                "title": "Geography",
                                "message": summary,
                                "variant": "info",
                                "duration": 12000,
                            }
                        }
                    ),
                },
            )
        redirect = (
            "/web/views/geo_data/geo_data.country.list"
            f"?pv_flash={quote(summary, safe='')}"
        )
        return RedirectResponse(redirect, status_code=303)
