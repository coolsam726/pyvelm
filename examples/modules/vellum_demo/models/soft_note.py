from pyvelm import BaseModel, fields
from pyvelm.vellum import SoftDeletes, Vellum


class DemoSoftNote(Vellum, BaseModel, SoftDeletes):
    """
    Soft delete note model with active field.
    """

    _name = "vellum.demo.soft_note"
    _rec_name = "title"

    title = fields.Char(required=True)
    deleted_at = fields.Datetime(string="Deleted At")
    active = fields.Boolean(default=True)
