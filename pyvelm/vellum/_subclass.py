"""Class-body checks for :class:`Vellum` models."""
from __future__ import annotations

import ast
import inspect
import textwrap


def _detect_field_method_collisions(cls) -> None:
    """Raise if a One2many/Many2many field shares a name with a method in the class body."""
    try:
        source = textwrap.dedent(inspect.getsource(cls))
    except (OSError, TypeError):
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != cls.__name__:
            continue
        field_names: set[str] = set()
        method_names: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef):
                method_names.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and _is_o2m_m2m_call(stmt.value):
                        field_names.add(target.id)
        overlap = field_names & method_names
        if overlap:
            name = sorted(overlap)[0]
            raise TypeError(
                f"{cls._name}.{name}: a relation method cannot share a name "
                f"with a One2many/Many2many field — remove the method or use "
                f"the field with with_('...') instead."
            )
        return


def _is_o2m_m2m_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in ("One2many", "Many2many")
    if isinstance(func, ast.Attribute):
        return func.attr in ("One2many", "Many2many")
    return False
