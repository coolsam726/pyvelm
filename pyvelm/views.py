"""View arch normalization, inheritance, and resolution.

The arch stored in `ir.ui.view.arch` is JSON, but its authoring form is
deliberately terse (`"fields": ["name", "age"]`). On the way in, the
normalizer promotes those shortcuts to addressable shapes
(`{"name": "name"}`); on the way out, the resolver walks the parent
chain and applies operations from every extension view in ascending
priority order.

Operation shape:
    {"op": "<set|replace|before|after|remove>",
     "target": [<key-or-name>, ...],
     "value": <dict, optional except for remove>}

Target resolution rule:
    - string segment + dict node      -> dict key lookup
    - string segment + list-of-dicts  -> match the dict whose `name` equals it
    - int segment    + list           -> positional index
"""
from __future__ import annotations

import copy
import json
from typing import Any

# Per-view_type list positions whose string entries should be promoted
# to {"name": <str>} dicts at normalization time. Extensible by adding
# more entries as new view_types land.
_LIST_PROMOTION_PATHS: dict[str, list[tuple[str, ...]]] = {
    "list": [("fields",)],
    # Form view: `sections` is a list of section dicts, each with its
    # own `fields` list. `*` means "every entry in this list" — so the
    # promotion applies to fields inside every section.
    "form": [("sections", "*", "fields")],
    # Kanban view: card.fields and card.badges are field-spec lists.
    # title/subtitle stay as plain strings (single-field references)
    # because addressing them by name doesn't help inheritance.
    "kanban": [("card", "fields"), ("card", "badges")],
}


def normalize_arch(arch: dict, view_type: str) -> dict:
    """Promote authoring-sugar strings to dicts in known list positions.

    Returns a new dict; never mutates the input. Idempotent — passing an
    already-normalized arch is a no-op.
    """
    if arch is None:
        return arch
    result = copy.deepcopy(arch)
    for path in _LIST_PROMOTION_PATHS.get(view_type, []):
        _promote_list_at(result, list(path))
    return result


def _promote_list_at(node: Any, path: list[str]) -> None:
    if not path:
        if isinstance(node, list):
            for i, item in enumerate(node):
                if isinstance(item, str):
                    node[i] = {"name": item}
        return
    head, *rest = path
    if head == "*":
        if isinstance(node, list):
            for item in node:
                _promote_list_at(item, rest)
        return
    if isinstance(node, dict) and head in node:
        _promote_list_at(node[head], rest)


# ----- target traversal -----

def _step_into(node: Any, seg: Any) -> Any:
    if isinstance(node, list):
        if isinstance(seg, int):
            return node[seg]
        if isinstance(seg, str):
            for item in node:
                if isinstance(item, dict) and item.get("name") == seg:
                    return item
            raise KeyError(f"no list entry named {seg!r}")
        raise TypeError(f"can't step into list with {type(seg).__name__}")
    if isinstance(node, dict):
        if isinstance(seg, str):
            if seg not in node:
                raise KeyError(f"no key {seg!r}")
            return node[seg]
    raise TypeError(f"can't step into {type(node).__name__} with {seg!r}")


def _resolve_position(parent: Any, seg: Any) -> Any:
    """Return the position (int index or str key) of `seg` inside `parent`."""
    if isinstance(parent, list):
        if isinstance(seg, int):
            if seg < 0 or seg >= len(parent):
                raise KeyError(f"index {seg} out of range")
            return seg
        if isinstance(seg, str):
            for i, item in enumerate(parent):
                if isinstance(item, dict) and item.get("name") == seg:
                    return i
            raise KeyError(f"no list entry named {seg!r}")
    if isinstance(parent, dict):
        if isinstance(seg, str):
            if seg not in parent:
                raise KeyError(f"no key {seg!r}")
            return seg
    raise TypeError(f"can't address {type(parent).__name__} with {seg!r}")


def apply_operations(arch: dict, operations: list[dict]) -> dict:
    """Apply each op to `arch` in order, in place. Returns the same dict.

    Caller should pass a deepcopy if they need the original preserved.
    """
    for op in operations:
        kind = op["op"]
        target = list(op["target"])

        # `update` walks all the way INTO the target (must end on a dict)
        # and merges in op["value"]. Equivalent to Odoo's
        # `position="attributes"` with multiple <attribute> children.
        if kind == "update":
            node = arch
            for seg in target:
                node = _step_into(node, seg)
            if not isinstance(node, dict):
                raise ValueError(
                    f"'update' target must resolve to a dict, got "
                    f"{type(node).__name__} at {target!r}"
                )
            value = op["value"]
            if not isinstance(value, dict):
                raise ValueError(
                    f"'update' value must be a dict, got {type(value).__name__}"
                )
            node.update(value)
            continue

        if not target:
            raise ValueError(f"Operation {op!r} has empty target")
        # Walk into the parent container.
        parent = arch
        for seg in target[:-1]:
            parent = _step_into(parent, seg)
        last = target[-1]

        if kind == "remove":
            position = _resolve_position(parent, last)
            del parent[position]
        elif kind in ("set", "replace"):
            # Granular attribute set: the final segment may be a new key
            # on a dict parent (think: add `readonly` to a field). Existing
            # keys are overwritten. Lists still require the entry to exist
            # — use `before`/`after` to grow a list.
            if isinstance(parent, dict) and isinstance(last, str):
                parent[last] = op["value"]
            else:
                position = _resolve_position(parent, last)
                parent[position] = op["value"]
        elif kind == "before":
            if not isinstance(parent, list):
                raise ValueError(
                    f"'before' requires a list parent, got "
                    f"{type(parent).__name__} at target {target!r}"
                )
            position = _resolve_position(parent, last)
            parent.insert(position, op["value"])
        elif kind == "after":
            if not isinstance(parent, list):
                raise ValueError(
                    f"'after' requires a list parent, got "
                    f"{type(parent).__name__} at target {target!r}"
                )
            position = _resolve_position(parent, last)
            parent.insert(position + 1, op["value"])
        else:
            raise ValueError(f"Unknown view-arch op: {kind!r}")
    return arch


# ----- chain resolution -----

def _ext_search(view, parent_id):
    """All extension views of parent_id, in ascending priority then id."""
    View = view.env["ir.ui.view"]
    return View.search(
        [("inherit_id", "=", parent_id)],
        order='"priority" ASC, "id" ASC',
    )


def resolve_arch(view) -> dict:
    """Return the fully-resolved arch for `view`.

    If `view` is an extension, walks up to the root base view first.
    Then applies every extension in the family in (priority, id) order.
    Depth-first: extensions-of-extensions are applied after their parent
    extension's ops, in the same priority sweep.
    """
    root = view
    while root.inherit_id:
        root = root.inherit_id
    if not root.arch:
        raise ValueError(
            f"View {root.module}.{root.name} has no arch (extension views "
            f"need an inherit_id to a base view)"
        )
    arch = copy.deepcopy(json.loads(root.arch))
    _apply_chain(root, arch)
    # Normalize the resolved arch so that any plain-string entries
    # inserted by before/after/replace operations are promoted to dicts.
    view_type = root.view_type
    if view_type:
        arch = normalize_arch(arch, view_type)
    return arch


def _apply_chain(view, arch):
    for ext in _ext_search(view, view.id):
        if ext.operations:
            ops = json.loads(ext.operations)
            apply_operations(arch, ops)
        _apply_chain(ext, arch)
