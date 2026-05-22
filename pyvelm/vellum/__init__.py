"""Vellum — optional Eloquent-style ergonomics on pyvelm recordsets.

Define models with the mixin::

    from pyvelm.vellum import Vellum

    class Post(Vellum, BaseModel):
        _name = "blog.post"

Query at runtime via the technical name (safe across ``_inherit``)::

    posts = env.query("blog.post").where("views", ">", 100).get()
"""
from .collection import wrap
from .counts import apply_with_counts
from .eager import eager_load
from .events import on
from .fillable import filter_mass_assignment
from .mixin import Vellum
from .query import QueryBuilder
from .relations import BelongsTo, BelongsToMany, HasMany, HasOne, Relation
from .scope import scope
from .soft_delete import SoftDeletes

__all__ = [
    "BelongsTo",
    "BelongsToMany",
    "HasMany",
    "HasOne",
    "QueryBuilder",
    "Relation",
    "SoftDeletes",
    "Vellum",
    "apply_with_counts",
    "eager_load",
    "filter_mass_assignment",
    "on",
    "scope",
    "wrap",
]
