"""``ir.attachment`` — generic file/blob storage attached to any record.

Each row associates one file with one (model, record-id) pair through
``res_model`` + ``res_id``. The two fields are deliberately schemaless
(no FK) so any model can grow attachments without a separate junction
table per host.

Field shape
-----------
name           Display name (usually the original filename).
datas_fname    Original filename as uploaded (preserved for download).
mimetype       Guessed via ``mimetypes.guess_type`` at upload time.
file_size      Bytes — denormalised so a list view can show it without
               touching the storage backend.
res_model      ``_name`` of the owning model (e.g. ``crm.lead``).
res_id         Primary key of the owning record. ``NULL`` for
               not-yet-attached uploads (e.g. on a brand-new form
               that hasn't saved its parent record yet).
type           ``binary`` (file blob) or ``url`` (link only — useful
               for external references like SharePoint URLs).
url            External URL when ``type='url'``; ignored otherwise.
storage_key    Opaque key handed back by the storage backend. Empty
               string for the ``db`` backend (datas column holds bytes).
datas          Inline bytes — populated by the ``db`` backend, ``NULL``
               by the ``local`` backend (which uses ``storage_key``).
"""

from __future__ import annotations

import base64

from pyvelm import BaseModel, Char, Integer, Text


class Attachment(BaseModel):
    _name = "ir.attachment"

    name = Char(required=True, string="Name")
    datas_fname = Char(string="Filename")
    mimetype = Char(default="application/octet-stream", string="Content Type")
    file_size = Integer(string="Size")
    res_model = Char(string="Linked Model")
    res_id = Integer(string="Linked Record")
    type = Char(default="binary", string="Type")
    url = Char(string="URL")
    storage_key = Char(string="Storage Key")
    datas = Text(string="Data")  # base64-encoded bytes for the db backend

    @property
    def display_name(self) -> str:
        self.ensure_one()
        return self.name or self.datas_fname or f"Attachment #{self.id}"

    # ---- bytes round-trip ----

    def fetch_content(self) -> bytes:
        """Read the actual bytes for a singleton attachment.

        Honours both backends: ``datas`` (db) decoded base64, or
        ``storage_key`` (local) loaded via the configured backend.
        Returns empty bytes for ``type='url'`` rows — callers should
        check ``type`` first if they care."""
        self.ensure_one()
        if self.type == "url":
            return b""
        if self.datas:
            try:
                return base64.b64decode(self.datas)
            except (ValueError, TypeError):
                return b""
        if self.storage_key:
            from pyvelm.storage import get_backend
            try:
                return get_backend().load(self.storage_key)
            except FileNotFoundError:
                return b""
        return b""

    # ---- cleanup ----

    def unlink(self) -> None:
        """Delete blob(s) from the backend before dropping rows.

        Errors from the backend are swallowed — a missing file is fine,
        and we don't want to block a DB delete on a storage hiccup.
        Worst case: a few orphan files in the storage dir, which a
        future GC pass can sweep."""
        from pyvelm.storage import get_backend
        backend = get_backend()
        # Snapshot keys before the DB rows go away (post-unlink the
        # records can't be re-read).
        keys: list[str] = []
        for rec in self:
            if rec.storage_key:
                keys.append(rec.storage_key)
        super().unlink()
        for key in keys:
            try:
                backend.delete(key)
            except Exception:  # noqa: BLE001
                pass
