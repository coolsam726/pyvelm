from __future__ import annotations

from typing import Iterator


class Registry:
    def __init__(self) -> None:
        self._models: dict[str, type] = {}
        # Built by init_db:
        #   _direct_deps[(model, field)] -> list[(dep_model, dep_field)]
        #   _m2o_deps[(comodel, field)]  -> list[(model, m2o_field, dep_field)]
        #   _stored_compute_order[model] -> [field, ...] (topo)
        self._direct_deps: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self._m2o_deps: dict[
            tuple[str, str], list[tuple[str, str, str]]
        ] = {}
        self._stored_compute_order: dict[str, list[str]] = {}

    def register(self, model_cls: type) -> None:
        self._models[model_cls._name] = model_cls

    def __getitem__(self, name: str) -> type:
        return self._models[name]

    def __contains__(self, name: str) -> bool:
        return name in self._models

    def __iter__(self) -> Iterator[type]:
        return iter(self._models.values())

    def init_db(self, conn) -> None:
        # Multi-pass init:
        #   1. CREATE TABLE for each model (no FKs yet) so any target exists.
        #   2. ALTER TABLE ADD CONSTRAINT for FK columns (handles forward refs
        #      and self-references).
        #   3. CREATE TABLE for Many2many junction tables; symmetric pairs
        #      dedupe via the `created_rels` set.
        #   4. Validate One2many inverses and Many2many comodels now that
        #      everything is in scope.
        for cls in self._models.values():
            cls._setup_table(conn)
        for cls in self._models.values():
            cls._setup_foreign_keys(conn, self)
        created_rels: set[str] = set()
        for cls in self._models.values():
            cls._setup_relation_tables(conn, self, created_rels)
        for cls in self._models.values():
            cls._validate_relations(self)
        self._build_compute_graph()

    def _build_compute_graph(self) -> None:
        """Parse @depends paths into the dep graph; detect cycles; topo-sort."""
        from .fields import Many2one

        self._direct_deps.clear()
        self._m2o_deps.clear()
        self._stored_compute_order.clear()

        # (model, field) -> list of (dep_model, dep_field) it reads from.
        # Used for cycle detection and topo sort. Same shape as the inverse
        # of _direct_deps + _m2o_deps but keyed the other way.
        read_edges: dict[tuple[str, str], list[tuple[str, str]]] = {}

        for cls in self._models.values():
            for fname, field in cls._fields.items():
                if not field.compute:
                    continue
                reads: list[tuple[str, str]] = []
                for path in field.depends_on:
                    tokens = path.split(".")
                    if len(tokens) > 2:
                        raise ValueError(
                            f"{cls._name}.{fname}: dep path {path!r} has more "
                            f"than one hop; deferred to a later stage"
                        )
                    head = tokens[0]
                    if head != "id" and head not in cls._fields:
                        raise ValueError(
                            f"{cls._name}.{fname}: dep {head!r} not a field"
                        )
                    if len(tokens) == 1:
                        self._direct_deps.setdefault(
                            (cls._name, head), []
                        ).append((cls._name, fname))
                        reads.append((cls._name, head))
                    else:
                        head_field = cls._fields[head]
                        if not isinstance(head_field, Many2one):
                            raise ValueError(
                                f"{cls._name}.{fname}: dep {path!r} requires "
                                f"{head!r} to be a Many2one (got "
                                f"{type(head_field).__name__})"
                            )
                        comodel = self._models[head_field.comodel_name]
                        tail = tokens[1]
                        if tail not in comodel._fields:
                            raise ValueError(
                                f"{cls._name}.{fname}: "
                                f"{head_field.comodel_name} has no field {tail!r}"
                            )
                        self._m2o_deps.setdefault(
                            (head_field.comodel_name, tail), []
                        ).append((cls._name, head, fname))
                        # Also: this compute reads the head FK itself, so any
                        # change to country_id should invalidate too.
                        self._direct_deps.setdefault(
                            (cls._name, head), []
                        ).append((cls._name, fname))
                        reads.append((cls._name, head))
                        reads.append((head_field.comodel_name, tail))
                read_edges[(cls._name, fname)] = reads

        # Cycle detection over the read graph restricted to compute fields.
        compute_nodes = set(read_edges.keys())
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[tuple[str, str], int] = {n: WHITE for n in compute_nodes}

        def dfs(node, stack):
            color[node] = GRAY
            for dep in read_edges.get(node, []):
                if dep not in compute_nodes:
                    continue  # non-compute dep — not in cycle search
                if color[dep] == GRAY:
                    cycle = stack[stack.index(dep):] + [dep]
                    raise ValueError(
                        "Computed-field cycle: "
                        + " -> ".join(f"{m}.{f}" for m, f in cycle)
                    )
                if color[dep] == WHITE:
                    dfs(dep, stack + [dep])
            color[node] = BLACK

        for n in compute_nodes:
            if color[n] == WHITE:
                dfs(n, [n])

        # Per-model topological order of stored compute fields (for create()).
        for cls in self._models.values():
            stored = [
                f for f, fld in cls._fields.items()
                if fld.compute and fld.is_stored
            ]
            order: list[str] = []
            seen: set[str] = set()

            def visit(fname):
                if fname in seen:
                    return
                for dep_model, dep_field in read_edges.get((cls._name, fname), []):
                    if dep_model == cls._name and dep_field in stored:
                        visit(dep_field)
                seen.add(fname)
                order.append(fname)

            for f in stored:
                visit(f)
            self._stored_compute_order[cls._name] = order

    def reset_db(self, conn) -> None:
        """Drop and recreate every registered model's table. Test-only."""
        from .fields import Many2many

        # Drop Many2many junction tables explicitly so stale schema can't
        # survive a failed prior run (CREATE TABLE IF NOT EXISTS would
        # otherwise silently skip recreation).
        relation_names: set[str] = set()
        for cls in self._models.values():
            for f in cls._fields.values():
                if isinstance(f, Many2many):
                    relation_names.add(f.resolve_spec(cls, self)[0])
        for rel in relation_names:
            conn.execute(f'DROP TABLE IF EXISTS "{rel}" CASCADE')
        for cls in self._models.values():
            cls._drop_table(conn)
        self.init_db(conn)


registry = Registry()
