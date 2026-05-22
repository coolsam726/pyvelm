from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator


# Active registry that newly-defined model classes register into.
# The loader sets this around each module's import; ad-hoc users set
# it via `with registry.activate():`. There is no module-global
# default — defining a model with no active registry is a programming
# error, not a silent fallback.
_active: contextvars.ContextVar["Registry | None"] = contextvars.ContextVar(
    "pyvelm_active_registry", default=None
)


def active_registry() -> "Registry":
    reg = _active.get()
    if reg is None:
        raise RuntimeError(
            "No active pyvelm registry. Define model classes inside a "
            "`with my_registry.activate():` block, or let the loader "
            "handle module imports."
        )
    return reg


class Registry:
    def __init__(self) -> None:
        self._models: dict[str, type] = {}
        # Which module each model came from, populated by the loader.
        # Modules use this to scope schema creation / migrations.
        self._model_module: dict[str, str] = {}
        # Which models were *extended* (via _inherit) by each module.
        # Maps  extension_module_name -> [model_name, ...]
        self._model_extensions: dict[str, list[str]] = {}
        # Built by init_db:
        #   _edge_index[(listen_model, listen_attr)] ->
        #       [(dep_model, dep_field, HopEdge), ...]
        #   _stored_compute_order[model] -> [field, ...] in topo order
        self._edge_index: dict[
            tuple[str, str], list[tuple[str, str, "HopEdge"]]
        ] = {}
        self._stored_compute_order: dict[str, list[str]] = {}

    @contextlib.contextmanager
    def activate(self):
        """Bind this registry as the active one for model class creation.

        Usage:
            with reg.activate():
                class Partner(BaseModel):
                    _name = "res.partner"
                    ...
        """
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)

    def register(self, model_cls: type, module_name: str | None = None) -> None:
        self._models[model_cls._name] = model_cls
        if module_name is not None:
            self._model_module[model_cls._name] = module_name

    def models_of(self, module_name: str) -> list[type]:
        """Models contributed by a single module, in registration order."""
        return [
            cls for cls in self._models.values()
            if self._model_module.get(cls._name) == module_name
        ]

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
        from .paths import parse_path

        self._edge_index.clear()
        self._stored_compute_order.clear()

        # (model, field) -> list of (dep_model, dep_field) it reads from.
        # Used for cycle detection and topo sort.
        read_edges: dict[tuple[str, str], list[tuple[str, str]]] = {}

        for cls in self._models.values():
            for fname, field in cls._fields.items():
                if not field.compute and not field.related:
                    continue
                reads: list[tuple[str, str]] = []
                for path_str in field.depends_on:
                    path = parse_path(cls, path_str, self)
                    for edge in path.edges():
                        self._edge_index.setdefault(edge.listen_at, []).append(
                            (cls._name, fname, edge)
                        )
                    reads.extend(path.reads())
                if field.compute:
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
