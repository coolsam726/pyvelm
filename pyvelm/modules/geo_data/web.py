"""On-demand geography seed — ``POST /web/geo-data/seed``."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from pyvelm import Environment
from pyvelm.request_env import apply_request_scope


def register_routes(app) -> None:
    registry = app.state.registry
    pool = app.state.pool

    def _resolve_session(env, token):
        if not token or "res.users" not in env.registry:
            return None
        env._acl_bypass = True
        try:
            users = env["res.users"].search(
                [("session_token", "=", token), ("active", "=", True)], limit=1
            )
            return users.id if users else None
        finally:
            env._acl_bypass = False

    def get_env(request: Request):
        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env = apply_request_scope(
                env, request, resolve_session=_resolve_session
            )
            yield env

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

        from geo_data.hooks import seed_reference_data

        try:
            with env.transaction():
                counts = seed_reference_data(env)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        parts = [
            f"{counts[k]} {k}"
            for k in ("continents", "countries", "states", "cities")
            if counts.get(k)
        ]
        summary = (
            "Geography data seeded"
            + (f" ({', '.join(parts)} added)" if parts else " (already up to date)")
        )
        redirect = (
            "/web/views/geo_data/geo_data.country.list"
            f"?pv_flash={quote(summary, safe='')}"
        )
        if request.headers.get("HX-Request"):
            return Response(status_code=200, headers={"HX-Redirect": redirect})
        return RedirectResponse(redirect, status_code=303)
