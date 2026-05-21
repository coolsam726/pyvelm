from __future__ import annotations

from typing import Callable


def depends(*paths: str) -> Callable:
    """Mark a compute method's dependencies.

    Same-record fields: `@depends('first_name', 'last_name')`.
    One-hop traversal through a Many2one: `@depends('country_id.name')`.
    Multi-hop and traversal through One2many/Many2many are deferred.

    The decorator just stashes the path tuple on the method; the metaclass
    later finds the field whose `compute=` names this method and copies
    `depends_on` onto the field.
    """

    def decorator(method: Callable) -> Callable:
        method._pyvelm_depends = paths  # type: ignore[attr-defined]
        return method

    return decorator
