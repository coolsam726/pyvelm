"""Extend ``ir.attachment`` with a computed thumbnail URL.

Used by the file_manager kanban (``image="thumbnail_url"``) and the
file picker dialog so image attachments render as visible tiles
without bespoke per-card markup. Non-image rows return an empty
string and the renderer falls back to the textual card.
"""

from __future__ import annotations

from pyvelm import BaseModel, Char, Many2one, depends


_IMAGE_MIME_PREFIX = "image/"


class Attachment(BaseModel):
    _inherit = "ir.attachment"

    # Non-stored Char: the value is derived from id + mimetype at read
    # time. Kept in the cache for the duration of a request via the
    # standard compute mechanism.
    thumbnail_url = Char(string="Thumbnail", compute="_compute_thumbnail_url")

    # Optional Drive-style folder grouping. Nullable on purpose —
    # attachments uploaded via the chatter / picker / record-bound
    # paths never carry a folder, and that's a valid "Unfiled" state.
    folder_id = Many2one(
        "res.attachment.folder", ondelete="SET NULL", string="Folder"
    )

    # Company stamp for the file library. NOT ``_company_scoped`` on the
    # model — ``ir.attachment`` backs avatars, mail, reports, etc. that
    # must stay cross-company. The library / picker queries filter on
    # this column explicitly instead, so only the *library UI* is
    # company-scoped while system attachments keep working.
    company_id = Many2one("res.company", ondelete="SET NULL", string="Company")

    @depends("id", "mimetype", "type", "url")
    def _compute_thumbnail_url(self):
        for r in self:
            mime = (r.mimetype or "").lower()
            if r.type == "url" and r.url and mime.startswith(_IMAGE_MIME_PREFIX):
                # External URL attachments: serve the external bytes
                # directly. The download endpoint is for stored rows.
                r.thumbnail_url = r.url
                continue
            if mime.startswith(_IMAGE_MIME_PREFIX) and r.id:
                r.thumbnail_url = f"/api/attachment/{r.id}/download"
            else:
                r.thumbnail_url = ""
