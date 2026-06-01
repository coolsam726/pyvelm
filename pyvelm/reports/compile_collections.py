"""Report column expressions — SQLAlchemy Core."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.sql.expression import ColumnElement, literal_column

from ..database.capabilities import DialectCapabilities
from ..database.dialects import dialect_capabilities
from ..database.sa_ddl import core_table
from ..fields import Float, Integer, Many2one, Many2many, One2many
from ..paths import M2mHop, M2oHop, O2mHop, Path, parse_path

if TYPE_CHECKING:
    from ..domain_sa import DomainCompiler


def default_subaggregate(leaf_field) -> str:
    if isinstance(leaf_field, (Integer, Float)):
        return "sum"
    return "string_agg"


def _resolve_m2m_spec(hop: M2mHop, source_cls, registry):
    return hop.field.resolve_spec(source_cls, registry)


def _qcol(alias: str, col_name: str) -> ColumnElement:
    bare = alias.strip('"')
    return literal_column(f'"{bare}"."{col_name}"')


def _root_id_col(root_alias: str) -> ColumnElement:
    return literal_column(f'{root_alias}."id"')


def _collection_aggregate(
    subaggregate: str,
    *,
    leaf_col: ColumnElement,
    coll_alias: str,
    leaf_cls,
    path: Path,
    current_alias: str,
    registry,
) -> ColumnElement:
    if subaggregate == "count":
        return func.count(func.distinct(_qcol(coll_alias, "id")))
    if subaggregate == "string_agg":
        leaf_field = leaf_cls._fields.get(path.leaf_attr)
        if isinstance(leaf_field, Many2one):
            comodel = registry[leaf_field.comodel_name]
            disp = (
                _qcol(current_alias, "name")
                if "name" in comodel._fields
                else leaf_col
            )
        else:
            disp = leaf_col
        disp_sql = str(disp)
        return literal_column(
            f"string_agg(DISTINCT {disp_sql}::text, ', ' ORDER BY {disp_sql}::text)"
        )
    if subaggregate in ("sum", "avg", "min", "max"):
        return getattr(func, subaggregate)(leaf_col)
    raise ValueError(f"Unknown subaggregate {subaggregate!r}")


def collection_subquery_expr(
    path: Path,
    root_cls,
    root_alias: str,
    registry,
    subaggregate: str | None,
    *,
    capabilities: DialectCapabilities | None = None,
) -> ColumnElement:
    """Correlated scalar subquery for paths through O2m/M2m."""
    if not path.hops:
        raise ValueError(f"Path {path.leaf_attr!r} has no relational hops")

    coll_idx = next(
        (i for i, h in enumerate(path.hops) if isinstance(h, (O2mHop, M2mHop))),
        None,
    )
    if coll_idx is None:
        raise ValueError("collection_subquery_expr called on m2o-only path")

    cap = capabilities or dialect_capabilities("postgresql")
    coll_hop = path.hops[coll_idx]
    target = registry[coll_hop.target_model]
    coll_alias = "_sqc"
    root_ref = _root_id_col(root_alias)

    if isinstance(coll_hop, O2mHop):
        inv_field = registry[coll_hop.target_model]._fields[coll_hop.inverse_attr]
        coll_tbl = core_table(
            target._table,
            cap,
            "id",
            inv_field.column,
            registry=registry,
            model_cls=target,
        ).alias(coll_alias)
        from_clause = coll_tbl
        correlate_where = _qcol(coll_alias, inv_field.column) == root_ref
    else:
        source_cls = registry[coll_hop.source_model]
        rel, col1, col2, _, _ = _resolve_m2m_spec(coll_hop, source_cls, registry)
        rel_tbl = core_table(rel, cap, col1, col2).alias("_sqrel")
        coll_tbl = core_table(target._table, cap, "id").alias(coll_alias)
        from_clause = rel_tbl.join(
            coll_tbl,
            _qcol(coll_alias, "id") == _qcol("_sqrel", col2),
        )
        correlate_where = _qcol("_sqrel", col1) == root_ref

    current_from = from_clause
    current_alias = coll_alias

    j = 0
    for hop in path.hops[coll_idx + 1 :]:
        if not isinstance(hop, M2oHop):
            raise ValueError(
                "Nested collection paths are not supported in report columns"
            )
        j += 1
        new_alias = f"_sqj{j}"
        tgt = registry[hop.target_model]
        hop_tbl = core_table(
            tgt._table,
            cap,
            "id",
            hop.field.column,
            registry=registry,
            model_cls=tgt,
        ).alias(new_alias)
        current_from = current_from.join(
            hop_tbl,
            _qcol(new_alias, "id") == _qcol(current_alias, hop.field.column),
            isouter=True,
        )
        current_alias = new_alias

    leaf_cls = registry[path.leaf_model]
    if path.leaf_attr == "id" and path.leaf_model == coll_hop.target_model:
        leaf_col = _qcol(coll_alias, "id")
    else:
        leaf_field = leaf_cls._fields[path.leaf_attr]
        leaf_col = _qcol(current_alias, leaf_field.column)

    if subaggregate is None:
        subaggregate = default_subaggregate(
            leaf_cls._fields.get(path.leaf_attr) if path.leaf_attr != "id" else Integer()
        )

    agg = _collection_aggregate(
        subaggregate,
        leaf_col=leaf_col,
        coll_alias=coll_alias,
        leaf_cls=leaf_cls,
        path=path,
        current_alias=current_alias,
        registry=registry,
    )
    return select(agg).select_from(current_from).where(correlate_where).scalar_subquery()


def column_expr_for_path(
    expr: str,
    root_cls,
    root_alias: str,
    registry,
    joins: list[str],
    join_aliases: dict,
    join_counter: list[int],
    subaggregate: str | None,
    *,
    compiler: "DomainCompiler | None" = None,
) -> tuple[ColumnElement, bool, str | None]:
    """Return a SELECT-list column expression for a report path."""
    if compiler is None:
        raise ValueError("column_expr_for_path requires a DomainCompiler")
    if expr == "id":
        return compiler._qcol(compiler._base_alias, "id"), False, None
    if "." not in expr:
        fld = root_cls._fields[expr]
        if isinstance(fld, (One2many, Many2many)):
            path = parse_path(root_cls, f"{expr}.id", registry)
            subq = collection_subquery_expr(
                path,
                root_cls,
                root_alias,
                registry,
                subaggregate or "count",
                capabilities=compiler.cap,
            )
            return subq, False, None
        is_m2o = isinstance(fld, Many2one)
        comodel = fld.comodel_name if is_m2o else None
        return compiler._qcol(compiler._base_alias, fld.column), is_m2o, comodel
    path = parse_path(root_cls, expr, registry)
    if path.is_m2o_only():
        alias = compiler._emit_m2o_chain(path.hops)
        leaf_cls = registry[path.leaf_model]
        leaf_field = leaf_cls._fields[path.leaf_attr]
        is_m2o = isinstance(leaf_field, Many2one)
        comodel = leaf_field.comodel_name if is_m2o else None
        return compiler._qcol(alias, leaf_field.column), is_m2o, comodel
    subq = collection_subquery_expr(
        path,
        root_cls,
        root_alias,
        registry,
        subaggregate,
        capabilities=compiler.cap,
    )
    return subq, False, None
