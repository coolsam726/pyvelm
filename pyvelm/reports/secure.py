"""Security helpers for report and export paths.

Exports must never load rows by raw id without passing record rules.
Use ``search_read`` (search then read) so ACL + rules + company scope
match list views.
"""
from __future__ import annotations

from typing import Any, Sequence


def search_read(
    env,
    model: str,
    domain: list | None = None,
    fields: Sequence[str] | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
    order: str | None = None,
) -> list[dict[str, Any]]:
    """Return records visible to ``env`` via ``search`` + ``read``."""
    Model = env[model]
    recs = Model.search(domain or [], limit=limit, offset=offset, order=order)
    if not recs:
        return []
    return recs.read(list(fields) if fields else None)
