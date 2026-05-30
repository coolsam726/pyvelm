"""Multi-database routing (v1.1+) — Postgres tenant selection in one process.

See docs/multi-database.md. v1.0 uses a single ``PYVELM_DSN``; when
``PYVELM_DATABASES`` lists extra databases, routing middleware and the
database selector UI bind requests to the matching pool and registry.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .database import create_database_from_dsn, normalize_dsn

if TYPE_CHECKING:
    from .database import Database
    from .registry import Registry


DATABASE_COOKIE = "pyvelm_db"
DEFAULT_DB_KEY = "default"
DB_PATH_PREFIX = "/web/db/"


@dataclass
class DatabaseRoute:
    """Registered tenant database."""

    key: str
    dsn: str
    label: str = ""


@dataclass
class DatabaseRegistry:
    """In-memory catalog of databases for routing."""

    routes: dict[str, DatabaseRoute] = field(default_factory=dict)

    def get(self, key: str) -> DatabaseRoute | None:
        return self.routes.get(key)

    def items(self):
        return self.routes.items()

    @classmethod
    def from_env(cls) -> DatabaseRegistry:
        """Parse ``PYVELM_DATABASES`` when set.

        Supported formats:

        * JSON list: ``[{"key": "tenant_a", "dsn": "postgresql://…", "label": "Tenant A"}]``
        * Comma-separated: ``tenant_a=postgresql://…,tenant_b=postgresql://…``
        """
        raw = (os.environ.get("PYVELM_DATABASES") or "").strip()
        if not raw:
            return cls()
        reg = cls()
        if raw.startswith("["):
            for item in json.loads(raw):
                key = str(item["key"]).strip()
                reg.routes[key] = DatabaseRoute(
                    key=key,
                    dsn=normalize_dsn(str(item["dsn"])),
                    label=str(item.get("label") or key),
                )
            return reg
        for part in raw.split(","):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, dsn = part.split("=", 1)
            key = key.strip()
            reg.routes[key] = DatabaseRoute(
                key=key,
                dsn=normalize_dsn(dsn.strip()),
                label=key,
            )
        return reg


def resolve_migrate_dsn(database_key: str | None = None) -> str:
    """DSN for migrate/CLI — ``PYVELM_DSN`` or a named tenant from ``PYVELM_DATABASES``."""
    from .database import require_dsn_from_env

    if not database_key:
        return normalize_dsn(require_dsn_from_env())
    catalog = DatabaseRegistry.from_env()
    route = catalog.get(database_key)
    if route is None:
        raise SystemExit(
            f"Unknown database {database_key!r}. "
            f"Known: {sorted(catalog.routes) or '(none — set PYVELM_DATABASES)'}"
        )
    return route.dsn


def resolve_database_key(request) -> str | None:
    """Select database key from cookie, path prefix, or host filter."""
    cookie = (request.cookies.get(DATABASE_COOKIE) or "").strip()
    if cookie:
        return cookie

    path = request.url.path
    if path.startswith(DB_PATH_PREFIX):
        rest = path[len(DB_PATH_PREFIX) :]
        key, sep, remainder = rest.partition("/")
        if key:
            new_path = f"/{remainder}" if remainder else "/"
            request.scope["path"] = new_path
            raw_path = request.scope.get("raw_path")
            if isinstance(raw_path, (bytes, bytearray)):
                request.scope["raw_path"] = new_path.encode("utf-8")
            return key

    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if not host:
        return None

    dbfilter = (os.environ.get("PYVELM_DBFILTER") or "").strip()
    if dbfilter:
        try:
            if not re.search(dbfilter, host):
                return None
        except re.error:
            return None

    catalog = getattr(request.app.state, "database_catalog", None)
    if catalog:
        for key in catalog.routes:
            if host == key or host.startswith(f"{key}."):
                return key
    return None


def get_request_db_key(request) -> str:
    key = resolve_database_key(request)
    pool_map = getattr(request.app.state, "pool_map", None)
    if pool_map and key and key in pool_map:
        return key
    return DEFAULT_DB_KEY


def get_request_database(app, request) -> Database | None:
    """Return :class:`~pyvelm.database.Database` for *request*, or the default."""
    key = get_request_db_key(request)
    pool_map = getattr(app.state, "pool_map", None)
    if pool_map and key in pool_map:
        return pool_map[key]
    return getattr(app.state, "database", None)


def get_request_pool(app, request):
    db = get_request_database(app, request)
    if db is not None:
        return db.pool
    return app.state.pool


def load_registry_for_connection(conn, module_roots) -> Registry:
    """Build a :class:`~pyvelm.registry.Registry` from installed modules on *conn*."""
    from . import Environment, Registry, loader
    from .policies import register_builtin_policies

    register_builtin_policies()
    reg = Registry()
    env = Environment(conn, registry=reg)
    specs = loader.discover(module_roots)
    ordered = loader.resolve_order(specs)
    to_load = loader.specs_to_install(env, ordered, install_all=False)
    for spec in to_load:
        loader._load_models(spec, reg)
    reg._build_o2m_inverse_index()
    reg._build_m2o_referrers_index()
    reg._build_m2m_relation_index()
    reg._build_compute_graph()
    for cls in reg._models.values():
        cls._validate_relations(reg)
    return reg


def get_request_registry(app, request) -> Registry:
    """Registry for the active database (lazy per-tenant cache)."""
    key = get_request_db_key(request)
    cache: dict[str, Registry] | None = getattr(app.state, "registry_cache", None)
    if cache is None:
        return app.state.registry
    if key in cache:
        return cache[key]
    module_roots = getattr(app.state, "module_roots", []) or []
    db = get_request_database(app, request)
    if db is None:
        return app.state.registry
    with db.connect() as conn:
        reg = load_registry_for_connection(conn, module_roots)
    cache[key] = reg
    return reg


def configure_app_databases(
    app,
    default_database: Database,
    boot_registry: Registry,
    module_roots: list,
) -> None:
    """Attach ``pool_map`` / ``registry_cache`` when ``PYVELM_DATABASES`` is set."""
    catalog = DatabaseRegistry.from_env()
    app.state.database_catalog = catalog
    pool_map: dict[str, Database] = {DEFAULT_DB_KEY: default_database}
    registry_cache: dict[str, Registry] = {DEFAULT_DB_KEY: boot_registry}
    for key, route in catalog.routes.items():
        if key == DEFAULT_DB_KEY:
            continue
        pool_map[key] = create_database_from_dsn(route.dsn)
    app.state.pool_map = pool_map
    app.state.registry_cache = registry_cache
    app.state.default_db_key = DEFAULT_DB_KEY


class DatabaseSelectorMiddleware:
    """Attach ``request.state.pyvelm_db_key`` before route handlers run."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            from starlette.requests import Request

            request = Request(scope, receive)
            scope.setdefault("state", {})
            scope["state"]["pyvelm_db_key"] = get_request_db_key(request)
        await self.app(scope, receive, send)


def list_selectable_databases(app) -> list[tuple[str, str]]:
    """Return ``(key, label)`` pairs for the database selector UI."""
    out: list[tuple[str, str]] = [(DEFAULT_DB_KEY, "Default")]
    catalog = getattr(app.state, "database_catalog", None)
    if not catalog:
        return out
    for key, route in sorted(catalog.routes.items()):
        if key == DEFAULT_DB_KEY:
            continue
        out.append((key, route.label or key))
    return out


def routing_enabled(app) -> bool:
    catalog = getattr(app.state, "database_catalog", None)
    return bool(catalog and catalog.routes)
