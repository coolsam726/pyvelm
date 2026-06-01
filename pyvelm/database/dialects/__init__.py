"""Registry of per-backend dialect helper modules."""
from __future__ import annotations

from types import ModuleType

from ..capabilities import DialectCapabilities, dialect_base_name
from . import mssql, mysql, oracle, postgresql, sqlite

_BACKENDS: dict[str, ModuleType] = {
    postgresql.NAME: postgresql,
    sqlite.NAME: sqlite,
    mysql.NAME: mysql,
    mssql.NAME: mssql,
    oracle.NAME: oracle,
}

_DEFAULT = postgresql


def get_backend(name: str) -> ModuleType:
    return _BACKENDS.get(dialect_base_name(name), _DEFAULT)


def dialect_capabilities(dialect_name: str) -> DialectCapabilities:
    return get_backend(dialect_name).CAPABILITIES


def normalize_dsn_with_dialects(dsn: str) -> str:
    """Apply legacy URL aliases via dialect modules."""
    for backend in _BACKENDS.values():
        normalize = getattr(backend, "normalize_dsn", None)
        if normalize is None:
            continue
        rewritten = normalize(dsn)
        if rewritten is not None:
            return rewritten
    return dsn


def configure_engine(engine, caps: DialectCapabilities) -> None:
    get_backend(caps.name).configure_engine(engine)
