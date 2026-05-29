"""Dotted-path parser, shared by the compute-field dep graph and the domain
compiler.

A `Path` is a parsed dotted reference like `country_id.region_id.name`. It
carries a sequence of relational `Hop` objects plus a leaf attr. Every hop
knows how to walk in reverse (used by invalidation propagation), and the
path knows how to emit the set of `HopEdge` entries that get indexed into
`Registry._edge_index`.

The cleanest mental model: hops walk forward when you traverse the relation
in a query; the same hops walk backward when a change downstream needs to
fan out upstream to invalidate dependent compute fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Callable, Sequence


class Hop:
    """One relational step on a path.

    Subclasses (`M2oHop`, `O2mHop`, `M2mHop`) implement `reverse_walk`,
    which translates ids on this hop's *target* model into ids on its
    *source* model.
    """

    def __init__(self, source_model: str, attr: str, field, target_model: str) -> None:
        self.source_model = source_model
        self.attr = attr
        self.field = field
        self.target_model = target_model

    def reverse_walk(self, env, ids: Sequence[int]) -> list[int]:
        raise NotImplementedError


class M2oHop(Hop):
    """Many2one: source has an FK column pointing at target."""

    def reverse_walk(self, env, ids):
        if not ids:
            return []
        src = env.registry[self.source_model]
        col = self.field.column
        placeholders = ",".join(["%s"] * len(ids))
        rows = env.conn.execute(
            f'SELECT "id" FROM "{src._table}" '
            f'WHERE "{col}" IN ({placeholders})',
            list(ids),
        ).fetchall()
        return [r[0] for r in rows]


class O2mHop(Hop):
    """One2many: source.<attr> is the collection of targets whose
    inverse Many2one points back at source."""

    def __init__(self, source_model, attr, field, target_model, inverse_attr):
        super().__init__(source_model, attr, field, target_model)
        self.inverse_attr = inverse_attr

    def reverse_walk(self, env, ids):
        if not ids:
            return []
        tgt = env.registry[self.target_model]
        col = tgt._fields[self.inverse_attr].column
        placeholders = ",".join(["%s"] * len(ids))
        rows = env.conn.execute(
            f'SELECT DISTINCT "{col}" FROM "{tgt._table}" '
            f'WHERE "id" IN ({placeholders}) AND "{col}" IS NOT NULL',
            list(ids),
        ).fetchall()
        return [r[0] for r in rows]


class M2mHop(Hop):
    """Many2many: source.<attr> is the set of targets co-listed in a
    junction table."""

    def __init__(
        self,
        source_model,
        attr,
        field,
        target_model,
        relation: str,
        col1: str,  # FK -> source
        col2: str,  # FK -> target
    ):
        super().__init__(source_model, attr, field, target_model)
        self.relation = relation
        self.col1 = col1
        self.col2 = col2

    def reverse_walk(self, env, ids):
        if not ids:
            return []
        placeholders = ",".join(["%s"] * len(ids))
        rows = env.conn.execute(
            f'SELECT DISTINCT "{self.col1}" FROM "{self.relation}" '
            f'WHERE "{self.col2}" IN ({placeholders})',
            list(ids),
        ).fetchall()
        return [r[0] for r in rows]


@dataclass
class HopEdge:
    """One listening point for invalidation.

    When the field at `listen_at` is written on `listened_ids`, the records
    on the path's *source* model that should be invalidated are found by:

        ids = to_source(env, listened_ids)
        for hop in reversed(hops_to_walk):
            ids = hop.reverse_walk(env, ids)
    """

    listen_at: tuple[str, str]
    to_source: Callable
    hops_to_walk: list[Hop] = dc_field(default_factory=list)

    def find_source_ids(self, env, listened_ids) -> list[int]:
        ids = self.to_source(env, listened_ids)
        for hop in reversed(self.hops_to_walk):
            if not ids:
                return []
            ids = hop.reverse_walk(env, ids)
        return ids


@dataclass
class Path:
    """A parsed dotted reference rooted at `source_model`."""

    source_model: str
    hops: list[Hop]
    leaf_model: str
    leaf_attr: str

    def is_m2o_only(self) -> bool:
        return all(isinstance(h, M2oHop) for h in self.hops)

    def reads(self) -> list[tuple[str, str]]:
        """Every (model, attr) this path reads. Used for cycle detection
        and topo sort of stored compute fields."""
        out = [(h.source_model, h.attr) for h in self.hops]
        out.append((self.leaf_model, self.leaf_attr))
        return out

    def edges(self) -> list[HopEdge]:
        """All listening points whose changes should invalidate the
        dependent compute field. One per hop, plus one for the leaf."""

        def identity(env, ids):
            return list(ids)

        out: list[HopEdge] = []
        for i, hop in enumerate(self.hops):
            if isinstance(hop, M2oHop):
                # Listening side is source-side; the changed records ARE on
                # source. Walk hops[:i] reverse to fan out further.
                out.append(HopEdge(
                    listen_at=(hop.source_model, hop.attr),
                    to_source=identity,
                    hops_to_walk=self.hops[:i],
                ))
            elif isinstance(hop, O2mHop):
                # Listen on the inverse M2o on the target side. When that
                # M2o changes on a child, the affected parent ids are the
                # new values of the M2o on those children — same operation
                # as the hop's reverse_walk.
                out.append(HopEdge(
                    listen_at=(hop.target_model, hop.inverse_attr),
                    to_source=hop.reverse_walk,
                    hops_to_walk=self.hops[:i],
                ))
            elif isinstance(hop, M2mHop):
                out.append(HopEdge(
                    listen_at=(hop.source_model, hop.attr),
                    to_source=identity,
                    hops_to_walk=self.hops[:i],
                ))
        # Leaf edge: listened ids are on the leaf model (= target of the
        # last hop); walk ALL hops in reverse to reach the source.
        out.append(HopEdge(
            listen_at=(self.leaf_model, self.leaf_attr),
            to_source=identity,
            hops_to_walk=self.hops,
        ))
        return out


def parse_path(model_cls, path: str, registry) -> Path:
    """Parse a dotted reference against `model_cls`.

    Every non-leaf token must name a relational field (Many2one, One2many,
    or Many2many). The leaf can be any field; usually a scalar.
    """
    from .fields import Many2many, Many2one, One2many

    tokens = path.split(".")
    if not tokens or any(not t for t in tokens):
        raise ValueError(f"Invalid path: {path!r}")
    hops: list[Hop] = []
    current = model_cls
    for i, attr in enumerate(tokens):
        is_last = i == len(tokens) - 1
        if attr == "id":
            if not is_last:
                raise ValueError(
                    f"Path {path!r} on {model_cls._name}: "
                    f"'id' must be the leaf of a dependency path"
                )
            return Path(
                source_model=model_cls._name,
                hops=hops,
                leaf_model=current._name,
                leaf_attr="id",
            )
        if attr not in current._fields:
            raise ValueError(
                f"Path {path!r} on {model_cls._name}: "
                f"{current._name!r} has no field {attr!r}"
            )
        field = current._fields[attr]
        if is_last:
            return Path(
                source_model=model_cls._name,
                hops=hops,
                leaf_model=current._name,
                leaf_attr=attr,
            )
        if isinstance(field, Many2one):
            comodel = registry[field.comodel_name]
            hops.append(M2oHop(current._name, attr, field, comodel._name))
            current = comodel
        elif isinstance(field, One2many):
            comodel = registry[field.comodel_name]
            hops.append(
                O2mHop(
                    current._name, attr, field, comodel._name, field.inverse_name
                )
            )
            current = comodel
        elif isinstance(field, Many2many):
            comodel = registry[field.comodel_name]
            relation, col1, col2, _, _ = field.resolve_spec(current, registry)
            hops.append(
                M2mHop(
                    current._name, attr, field, comodel._name,
                    relation, col1, col2,
                )
            )
            current = comodel
        else:
            raise ValueError(
                f"Path {path!r} on {model_cls._name}: "
                f"{current._name}.{attr} is not relational "
                f"(got {type(field).__name__})"
            )
    raise RuntimeError("unreachable")  # tokens is non-empty  # pragma: no cover
