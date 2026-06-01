"""Domain → SQLAlchemy Core compiler.

Compiles Odoo-style domains into SQLAlchemy column expressions and SELECT
statements so search/count paths do not hand-build WHERE/JOIN SQL strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    ColumnElement,
    and_,
    column,
    exists,
    false,
    func,
    not_,
    or_,
    select,
    table,
    true,
)
from sqlalchemy.sql import FromClause, Select
from sqlalchemy.sql.expression import literal_column

from .database.capabilities import DialectCapabilities
from .database.dialects import dialect_capabilities
from .domain import (
    _ALL_FAIL_OPS,
    _SIMPLE_OPS,
    _coerce,
    _parse_leaf,
    _parse_polish,
    _resolve_simple,
    expand_or_groups,
    normalize_domain,
)
from .paths import M2mHop, M2oHop, O2mHop, parse_path


@dataclass
class _Join:
    target_table: str
    alias: str
    onclause: ColumnElement


class DomainCompiler:
    """Compile a normalized domain tree to SQLAlchemy Core expressions."""

    def __init__(
        self,
        model_cls,
        registry,
        cap: DialectCapabilities | None = None,
        *,
        shared_joins: list[str] | None = None,
        join_aliases: dict[tuple, str] | None = None,
        join_counter: list[int] | None = None,
    ) -> None:
        self.model_cls = model_cls
        self.registry = registry
        self.cap = cap or dialect_capabilities("postgresql")
        self.base_name = model_cls._table
        from .database.sa_ddl import core_table

        self.base = core_table(
            self.base_name,
            self.cap,
            "id",
            registry=registry,
            model_cls=model_cls,
        )
        self._base_alias = self.base_name
        self._shared_joins = shared_joins
        self._join_aliases = join_aliases if join_aliases is not None else {}
        self._join_counter = join_counter if join_counter is not None else [0]
        self._string_joins: list[str] = (
            shared_joins if shared_joins is not None else []
        )
        self._joins: list[_Join] = []

    def _next_alias(self, prefix: str = "_j") -> str:
        self._join_counter[0] += 1
        return f"{prefix}{self._join_counter[0]}"

    def _aliased_table(self, table_name: str, alias: str):
        from .database.sa_ddl import core_table

        return core_table(
            table_name,
            self.cap,
            "id",
            registry=self.registry,
        ).alias(alias)

    def _qcol(self, alias: str, col_name: str) -> ColumnElement:
        return literal_column(f'"{alias}"."{col_name}"')

    def _text_predicate(
        self, col: ColumnElement, op: str, value: Any, field_obj: Any | None
    ) -> ColumnElement:
        if self.cap.name == "oracle" and field_obj is not None:
            if getattr(field_obj, "sql_type", None) == "text" and op in ("=", "!="):
                cmp_expr = func.dbms_lob.compare(col, func.to_clob(value))
                zero = literal_column("0")
                return cmp_expr == zero if op == "=" else cmp_expr != zero
        if op == "=":
            return col == value
        if op == "!=":
            return col != value
        if op == "<":
            return col < value
        if op == "<=":
            return col <= value
        if op == ">":
            return col > value
        if op == ">=":
            return col >= value
        raise ValueError(f"Unsupported text predicate op {op!r}")

    def _ilike(self, col: ColumnElement, value: Any) -> ColumnElement:
        if self.cap.supports_ilike:
            return col.ilike(value)
        return func.lower(col).like(func.lower(value))

    def _emit_m2o_chain(self, hops) -> str:
        key: tuple = (self.base_name,)
        current_alias = self._base_alias
        for hop in hops:
            if not isinstance(hop, M2oHop):
                raise NotImplementedError(
                    f"Domain traversal through {type(hop).__name__}.{hop.attr} "
                    "not supported yet"
                )
            key = key + (hop.attr,)
            if key in self._join_aliases:
                current_alias = self._join_aliases[key]
                continue
            alias = self._next_alias()
            target = self.registry[hop.target_model]
            onclause = self._qcol(alias, "id") == self._qcol(
                current_alias, hop.field.column
            )
            self._join_aliases[key] = alias
            join_sql = (
                f'LEFT JOIN "{target._table}" {alias} ON '
                f'"{alias}"."id" = "{current_alias}"."{hop.field.column}"'
            )
            self._string_joins.append(join_sql)
            self._joins.append(_Join(target._table, alias, onclause))
            current_alias = alias
        return current_alias

    def _resolve_leaf_field(self, path):
        leaf_cls = self.registry[path.leaf_model]
        if path.leaf_attr == "id":
            return None
        leaf_field = leaf_cls._fields.get(path.leaf_attr)
        if leaf_field is None:
            raise ValueError(
                f"Path on {self.model_cls._name}: {path.leaf_model} has no field "
                f"{path.leaf_attr!r}"
            )
        return leaf_field

    def _exists_for_path(
        self, path, op: str, value: Any, *, universal: bool = False
    ) -> ColumnElement:
        if universal and op not in _ALL_FAIL_OPS and op not in ("like", "ilike"):
            raise ValueError(
                f"Operator {op!r} does not support {{'all': True}} on collection paths"
            )
        leaf_op = op
        if universal and op in _ALL_FAIL_OPS:
            leaf_op = _ALL_FAIL_OPS[op]

        if leaf_op == "in":
            if not list(value or ()):
                return true() if universal else false()
        if leaf_op == "not in":
            if not list(value or ()):
                return true()

        suffix = self._next_alias("_e")
        from_clause: Any = None
        inner: list[ColumnElement] = []
        prev_alias: str | None = None

        for i, hop in enumerate(path.hops):
            if isinstance(hop, O2mHop):
                tgt = self.registry[hop.target_model]
                inverse_col = tgt._fields[hop.inverse_attr].column
                alias = f"{suffix}_{i}"
                hop_tbl = self._aliased_table(tgt._table, alias)
                if i == 0:
                    inner.append(
                        self._qcol(alias, inverse_col) == self._qcol(
                            self._base_alias, "id"
                        )
                    )
                    from_clause = hop_tbl
                else:
                    inner.append(
                        self._qcol(alias, inverse_col)
                        == self._qcol(prev_alias, "id")
                    )
                    from_clause = from_clause.join(hop_tbl, inner[-1])
                prev_alias = alias
            elif isinstance(hop, M2mHop):
                j_alias = f"{suffix}_{i}j"
                t_alias = f"{suffix}_{i}t"
                tgt = self.registry[hop.target_model]
                from .database.sa_ddl import core_table

                rel_tbl = core_table(
                    hop.relation,
                    self.cap,
                    hop.col1,
                    hop.col2,
                    registry=self.registry,
                ).alias(j_alias)
                tgt_tbl = self._aliased_table(tgt._table, t_alias)
                if i == 0:
                    inner.append(
                        self._qcol(j_alias, hop.col1)
                        == self._qcol(self._base_alias, "id")
                    )
                    from_clause = rel_tbl
                else:
                    inner.append(
                        self._qcol(j_alias, hop.col1) == self._qcol(prev_alias, "id")
                    )
                    from_clause = from_clause.join(rel_tbl, inner[-1])
                inner.append(self._qcol(t_alias, "id") == self._qcol(j_alias, hop.col2))
                from_clause = from_clause.join(
                    tgt_tbl, self._qcol(t_alias, "id") == self._qcol(j_alias, hop.col2)
                )
                prev_alias = t_alias
            elif isinstance(hop, M2oHop):
                tgt = self.registry[hop.target_model]
                alias = f"{suffix}_{i}"
                hop_tbl = self._aliased_table(tgt._table, alias)
                if i == 0:
                    inner.append(
                        self._qcol(alias, "id")
                        == self._qcol(self._base_alias, hop.field.column)
                    )
                    from_clause = hop_tbl
                else:
                    inner.append(
                        self._qcol(alias, "id")
                        == self._qcol(prev_alias, hop.field.column)
                    )
                    from_clause = from_clause.join(hop_tbl, inner[-1])
                prev_alias = alias

        leaf_field = self._resolve_leaf_field(path)
        leaf_col = "id" if leaf_field is None else leaf_field.column
        col = self._qcol(prev_alias, leaf_col)
        inner.append(
            self._compile_leaf_predicate(
                col, leaf_op, value, leaf_field, universal=universal, raw_op=op
            )
        )

        subq = select(literal_column("1")).select_from(from_clause).where(
            and_(*inner)
        )
        exists_expr = exists(subq)
        return not_(exists_expr) if universal else exists_expr

    def _compile_leaf_predicate(
        self,
        col: ColumnElement,
        op: str,
        value: Any,
        field_obj: Any | None,
        *,
        universal: bool = False,
        raw_op: str | None = None,
    ) -> ColumnElement:
        if op in _SIMPLE_OPS:
            v = _coerce(field_obj, value)
            if v is None and op == "=":
                return col.is_(None)
            if v is None and op == "!=":
                return col.is_not(None)
            return self._text_predicate(col, op, v, field_obj)
        if op == "in":
            values = [_coerce(field_obj, v) for v in value]
            if not values:
                return false() if not universal else true()
            return col.in_(values)
        if op == "not in":
            values = [_coerce(field_obj, v) for v in value]
            if not values:
                return true()
            return col.not_in(values)
        raw = raw_op or op
        if universal and raw == "like":
            return col.notlike(value)
        if universal and raw == "ilike":
            return not_(self._ilike(col, value))
        if op == "like":
            return col.like(value)
        if op == "ilike":
            return self._ilike(col, value)
        raise ValueError(f"Unknown operator: {op!r}")

    def _leaf_col(self, attr: str) -> tuple[ColumnElement, Any | None]:
        if "." not in attr:
            col_name, field = _resolve_simple(self.model_cls, attr)
            return self._qcol(self._base_alias, col_name), field
        path = parse_path(self.model_cls, attr, self.registry)
        leaf_alias = self._emit_m2o_chain(path.hops)
        if path.leaf_attr == "id":
            return self._qcol(leaf_alias, "id"), None
        leaf_field = self.registry[path.leaf_model]._fields.get(path.leaf_attr)
        if leaf_field is None:
            raise ValueError(
                f"Path {attr!r}: {path.leaf_model} has no field {path.leaf_attr!r}"
            )
        return self._qcol(leaf_alias, leaf_field.column), leaf_field

    def _compile_leaf(self, leaf) -> ColumnElement:
        attr, op, value, universal = _parse_leaf(leaf)
        if universal and "." not in attr:
            raise ValueError(
                f"{{'all': True}} only applies to collection paths, got {attr!r}"
            )
        if "." in attr:
            path = parse_path(self.model_cls, attr, self.registry)
            if not path.is_m2o_only():
                return self._exists_for_path(path, op, value, universal=universal)
        col, field = self._leaf_col(attr)
        return self._compile_leaf_predicate(
            col, op, value, field, universal=universal, raw_op=op
        )

    def _compile_tree(self, node) -> ColumnElement:
        kind = node[0]
        if kind == "leaf":
            return self._compile_leaf(node[1])
        if kind == "!":
            return not_(self._compile_tree(node[1]))
        if kind == "&":
            return and_(self._compile_tree(node[1]), self._compile_tree(node[2]))
        if kind == "|":
            return or_(self._compile_tree(node[1]), self._compile_tree(node[2]))
        raise ValueError(f"Unknown domain node {kind!r}")

    def compile_where(self, domain) -> ColumnElement:
        if not domain:
            return true()
        domain_norm = normalize_domain(expand_or_groups(list(domain)))
        tree, end = _parse_polish(domain_norm, 0)
        if end != len(domain_norm):
            raise ValueError("Trailing tokens in domain")
        return self._compile_tree(tree)

    def from_clause(self) -> FromClause:
        from_clause: FromClause = self.base
        for j in self._joins:
            target = self._aliased_table(j.target_table, j.alias)
            from_clause = from_clause.join(target, j.onclause, isouter=True)
        return from_clause

    def joins_sql(self) -> str:
        if self._shared_joins is not None:
            return ""
        return (" " + " ".join(self._string_joins)) if self._string_joins else ""


def _sa_dialect(cap: DialectCapabilities):
    if cap.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.dialect()
    if cap.name == "sqlite":
        from sqlalchemy.dialects import sqlite

        return sqlite.dialect()
    if cap.name == "mysql":
        from sqlalchemy.dialects import mysql

        return mysql.dialect()
    if cap.name == "mssql":
        from sqlalchemy.dialects import mssql

        return mssql.dialect()
    if cap.name == "oracle":
        from sqlalchemy.dialects import oracle

        return oracle.dialect()
    raise ValueError(f"Unsupported dialect {cap.name!r}")


def _compiled_params(compiled) -> list[Any]:
    if not compiled.params:
        return []
    pos = getattr(compiled, "positiontup", None)
    if pos:
        return [compiled.params[key] for key in pos]
    return list(compiled.params.values())


def _normalize_compiled_sql(sql: str, cap: DialectCapabilities) -> str:
    if "%(" in sql:
        sql = re.sub(r"%\(\w+\)s", "%s", sql)
    sql = re.sub(r"\btrue\b", "TRUE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bfalse\b", "FALSE", sql, flags=re.IGNORECASE)
    if cap.name == "oracle":
        idx = 0

        def _oracle_bind(_match: re.Match[str]) -> str:
            nonlocal idx
            idx += 1
            return f":{idx}"

        sql = re.sub(r":\w+", _oracle_bind, sql)
    return sql


def clause_to_driver_sql(
    clause: ColumnElement, cap: DialectCapabilities
) -> tuple[str, list[Any]]:
    """Render a SQLAlchemy WHERE clause to driver SQL and positional params."""
    compiled = clause.compile(
        dialect=_sa_dialect(cap),
        compile_kwargs={"render_postcompile": True},
    )
    return _normalize_compiled_sql(str(compiled), cap), _compiled_params(compiled)


def column_element_to_sql(
    expr: ColumnElement, cap: DialectCapabilities
) -> str:
    """Render a single SELECT-list expression to SQL (no alias)."""
    compiled = select(expr).compile(
        dialect=_sa_dialect(cap),
        compile_kwargs={"render_postcompile": True},
    )
    sql = str(compiled).strip()
    if sql.upper().startswith("SELECT "):
        sql = sql[7:].strip()
    return _normalize_compiled_sql(sql, cap)


def statement_to_driver_sql(
    stmt: Select, cap: DialectCapabilities
) -> tuple[str, list[Any]]:
    """Render a SQLAlchemy SELECT to driver SQL and positional params."""
    compiled = stmt.compile(
        dialect=_sa_dialect(cap),
        compile_kwargs={"render_postcompile": True},
    )
    return _normalize_compiled_sql(str(compiled), cap), _compiled_params(compiled)


def apply_search_pagination(
    stmt: Select,
    cap: DialectCapabilities,
    *,
    base_table: str,
    limit: int | None,
    offset: int,
    has_order: bool,
) -> Select:
    """Apply offset/limit with Oracle/MSSQL stable-order requirements."""
    if limit is None and not offset:
        return stmt
    if cap.name in ("oracle", "mssql") and not has_order:
        stmt = stmt.order_by(literal_column(f'"{base_table}"."id"'))
    if offset:
        stmt = stmt.offset(int(offset))
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return stmt


def domain_to_sql(
    domain,
    model_cls,
    registry,
    *,
    capabilities: DialectCapabilities | None = None,
    joins: list[str] | None = None,
    join_aliases: dict[tuple, str] | None = None,
    join_counter: list[int] | None = None,
) -> tuple[str, list[Any], str]:
    """Legacy-compatible domain SQL (WHERE string, params, joins fragment)."""
    cap = capabilities or dialect_capabilities("postgresql")
    where_col, joins_sql = compile_domain_where(
        domain,
        model_cls,
        registry,
        capabilities=cap,
        joins=joins,
        join_aliases=join_aliases,
        join_counter=join_counter,
    )
    where_sql, params = clause_to_driver_sql(where_col, cap)
    return where_sql, params, joins_sql


def compile_domain_where(
    domain,
    model_cls,
    registry,
    *,
    capabilities: DialectCapabilities | None = None,
    joins: list[str] | None = None,
    join_aliases: dict[tuple, str] | None = None,
    join_counter: list[int] | None = None,
) -> tuple[ColumnElement, str]:
    """Return (WHERE expression, joins SQL fragment for legacy callers)."""
    compiler = DomainCompiler(
        model_cls,
        registry,
        capabilities,
        shared_joins=joins,
        join_aliases=join_aliases,
        join_counter=join_counter,
    )
    return compiler.compile_where(domain), compiler.joins_sql()


def domain_search_select(
    model_cls,
    domain,
    registry,
    *,
    capabilities: DialectCapabilities | None = None,
    order: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> Select:
    """Build a SQLAlchemy SELECT returning base-table ids for *domain*."""
    from sqlalchemy.sql.expression import text as sa_text

    cap = capabilities or dialect_capabilities("postgresql")
    compiler = DomainCompiler(model_cls, registry, cap)
    where = compiler.compile_where(domain)
    stmt = select(compiler.base.c.id).select_from(compiler.from_clause()).where(
        where
    )
    if order:
        stmt = stmt.order_by(sa_text(order))
    elif cap.name == "oracle" and (limit is not None or offset):
        stmt = stmt.order_by(compiler.base.c.id)
    if offset:
        stmt = stmt.offset(int(offset))
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return stmt


def domain_search_count_select(
    model_cls,
    domain,
    registry,
    *,
    capabilities: DialectCapabilities | None = None,
) -> Select:
    cap = capabilities or dialect_capabilities("postgresql")
    compiler = DomainCompiler(model_cls, registry, cap)
    where = compiler.compile_where(domain)
    return select(func.count()).select_from(compiler.from_clause()).where(where)


def domain_grouped_select(
    model_cls,
    domain,
    registry,
    select_columns: list,
    group_by: list | None,
    *,
    capabilities: DialectCapabilities | None = None,
    order: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> Select:
    """Build a grouped SELECT with domain filter via SQLAlchemy Core."""
    from sqlalchemy.sql.expression import text as sa_text

    cap = capabilities or dialect_capabilities("postgresql")
    compiler = DomainCompiler(model_cls, registry, cap)
    where = compiler.compile_where(domain)
    stmt = select(*select_columns).select_from(compiler.from_clause()).where(where)
    if group_by:
        stmt = stmt.group_by(*group_by)
    if order:
        stmt = stmt.order_by(sa_text(order))
    elif group_by:
        stmt = stmt.order_by(*group_by)
    elif cap.name == "oracle" and (limit is not None or offset):
        stmt = stmt.order_by(compiler.base.c.id)
    if offset:
        stmt = stmt.offset(int(offset))
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return stmt
