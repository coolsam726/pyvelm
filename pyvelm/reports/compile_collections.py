"""SQL subqueries for One2many / Many2many report columns."""
from __future__ import annotations

from ..fields import Float, Integer, Many2one, One2many, Many2many, Text
from ..paths import M2mHop, M2oHop, O2mHop, Path, parse_path


def default_subaggregate(leaf_field) -> str:
    if isinstance(leaf_field, (Integer, Float)):
        return "sum"
    return "string_agg"


def _resolve_m2m_spec(hop: M2mHop, source_cls, registry):
    return hop.field.resolve_spec(source_cls, registry)


def collection_subquery_sql(
    path: Path,
    root_cls,
    root_alias: str,
    registry,
    subaggregate: str | None,
) -> str:
    """Build a correlated scalar subquery for paths through O2m/M2m."""
    if not path.hops:
        raise ValueError(f"Path {path.leaf_attr!r} has no relational hops")

    coll_idx = next(
        (i for i, h in enumerate(path.hops) if isinstance(h, (O2mHop, M2mHop))),
        None,
    )
    if coll_idx is None:
        raise ValueError("collection_subquery_sql called on m2o-only path")

    coll_hop = path.hops[coll_idx]
    target = registry[coll_hop.target_model]
    coll_alias = "_sqc"
    join_parts: list[str] = []
    current_alias = coll_alias

    if isinstance(coll_hop, O2mHop):
        inv_field = registry[coll_hop.target_model]._fields[coll_hop.inverse_attr]
        from_sql = f'FROM "{target._table}" {coll_alias}'
        where_sql = (
            f'{coll_alias}."{inv_field.column}" = {root_alias}."id"'
        )
    else:
        source_cls = registry[coll_hop.source_model]
        rel, col1, col2, _, _ = _resolve_m2m_spec(coll_hop, source_cls, registry)
        from_sql = (
            f'FROM "{rel}" _sqrel '
            f'JOIN "{target._table}" {coll_alias} '
            f'ON {coll_alias}."id" = _sqrel."{col2}"'
        )
        root_fk = registry[coll_hop.source_model]._fields.get("id")
        where_sql = f'_sqrel."{col1}" = {root_alias}."id"'

    # Joins for m2o hops after the collection hop
    j = 0
    for hop in path.hops[coll_idx + 1 :]:
        if not isinstance(hop, M2oHop):
            raise ValueError(
                "Nested collection paths are not supported in report columns"
            )
        j += 1
        new_alias = f"_sqj{j}"
        tgt = registry[hop.target_model]
        join_parts.append(
            f'LEFT JOIN "{tgt._table}" {new_alias} ON '
            f'{new_alias}."id" = {current_alias}."{hop.field.column}"'
        )
        current_alias = new_alias

    leaf_cls = registry[path.leaf_model]
    if path.leaf_attr == "id" and path.leaf_model == coll_hop.target_model:
        leaf_col = f'{coll_alias}."id"'
    else:
        leaf_field = leaf_cls._fields[path.leaf_attr]
        leaf_col = f'{current_alias}."{leaf_field.column}"'

    if subaggregate is None:
        subaggregate = default_subaggregate(
            leaf_cls._fields.get(path.leaf_attr) if path.leaf_attr != "id" else Integer()
        )

    if subaggregate == "count":
        inner = f"COUNT(DISTINCT {coll_alias}.\"id\")"
    elif subaggregate == "string_agg":
        if isinstance(leaf_cls._fields.get(path.leaf_attr), Many2one):
            comodel = registry[leaf_cls._fields[path.leaf_attr].comodel_name]
            if "name" in comodel._fields:
                disp = f'{current_alias}."name"'
            else:
                disp = leaf_col
            inner = f"string_agg(DISTINCT {disp}::text, ', ' ORDER BY {disp}::text)"
        else:
            inner = (
                f"string_agg(DISTINCT {leaf_col}::text, ', ' ORDER BY {leaf_col}::text)"
            )
    elif subaggregate in ("sum", "avg", "min", "max"):
        inner = f"{subaggregate.upper()}({leaf_col})"
    else:
        raise ValueError(f"Unknown subaggregate {subaggregate!r}")

    joins_sql = " ".join(join_parts)
    return f"(SELECT {inner} {from_sql} {joins_sql} WHERE {where_sql})"


def column_sql_for_path(
    expr: str,
    root_cls,
    root_alias: str,
    registry,
    joins: list[str],
    join_aliases: dict,
    join_counter: list[int],
    subaggregate: str | None,
) -> tuple[str, bool, str | None]:
    """Dispatch scalar/m2o join vs collection subquery."""
    if expr == "id":
        return f'{root_alias}."id"', False, None
    if "." not in expr:
        fld = root_cls._fields[expr]
        if isinstance(fld, (One2many, Many2many)):
            path = parse_path(root_cls, f"{expr}.id", registry)
            sql = collection_subquery_sql(
                path, root_cls, root_alias, registry, subaggregate or "count",
            )
            return sql, False, None
        is_m2o = isinstance(fld, Many2one)
        comodel = fld.comodel_name if is_m2o else None
        return f'{root_alias}."{fld.column}"', is_m2o, comodel

    path = parse_path(root_cls, expr, registry)
    if path.is_m2o_only():
        alias = _emit_m2o_joins(
            path.hops, root_alias, registry, joins, join_aliases, join_counter
        )
        leaf_cls = registry[path.leaf_model]
        leaf_field = leaf_cls._fields[path.leaf_attr]
        is_m2o = isinstance(leaf_field, Many2one)
        comodel = leaf_field.comodel_name if is_m2o else None
        return f'{alias}."{leaf_field.column}"', is_m2o, comodel

    sql = collection_subquery_sql(path, root_cls, root_alias, registry, subaggregate)
    return sql, False, None


def _emit_m2o_joins(
    hops,
    base_alias: str,
    registry,
    joins: list[str],
    join_aliases: dict[tuple, str],
    join_counter: list[int],
) -> str:
    current_alias = base_alias
    key: tuple = (base_alias,)
    for hop in hops:
        if not isinstance(hop, M2oHop):
            raise ValueError(
                f"Report joins only support Many2one chains, got {type(hop).__name__}"
            )
        key = key + (hop.attr,)
        if key in join_aliases:
            current_alias = join_aliases[key]
            continue
        join_counter[0] += 1
        new_alias = f"_j{join_counter[0]}"
        target = registry[hop.target_model]
        joins.append(
            f'LEFT JOIN "{target._table}" {new_alias} ON '
            f'{new_alias}."id" = {current_alias}."{hop.field.column}"'
        )
        join_aliases[key] = new_alias
        current_alias = new_alias
    return current_alias
