"""``res.attachment.folder`` — hierarchical folders for the file library.

Folders are an optional organisational layer over ``ir.attachment``.
``folder_id`` on each attachment is nullable, so "Unfiled" works out of
the box for any pre-existing or composer-created row.

``parent_id`` uses ``ondelete="RESTRICT"`` so we can guard the
empty-check in the delete endpoint — Postgres will not let us drop a
folder that still has children, regardless of what the application
layer asks for.

The computed ``display_name`` walks up the parent chain (capped at
``_MAX_DEPTH`` to defuse accidental cycles) and renders a slash
breadcrumb like ``Marketing / Logos / 2026``.
"""

from __future__ import annotations

from pyvelm import BaseModel, Char, Integer, Many2one, depends


_MAX_DEPTH = 32


class AttachmentFolder(BaseModel):
    _name = "res.attachment.folder"
    _rec_name = "name"
    # Folders belong to a company: the framework auto-injects a
    # ``company_id`` Many2one and filters every ``search`` by
    # ``env.company_id`` when a company scope is active. Safe to opt in
    # here because this model is owned by file_manager (unlike the
    # shared ``ir.attachment``).
    _company_scoped = True

    name = Char(required=True, string="Name")
    parent_id = Many2one(
        "res.attachment.folder", ondelete="RESTRICT", string="Parent"
    )
    sequence = Integer(default=10, string="Sequence")
    color = Char(string="Color")

    @depends("name", "parent_id")
    def _compute_display_name(self):
        for r in self:
            parts: list[str] = []
            node = r
            for _ in range(_MAX_DEPTH):
                if not node:
                    break
                name = (getattr(node, "name", None) or "").strip()
                if not name:
                    break
                parts.append(name)
                node = node.parent_id
                if not node or not getattr(node, "_ids", ()):
                    break
            r.display_name = " / ".join(reversed(parts)) or (
                r.name or f"res.attachment.folder #{r.id}"
            )
