from pyvelm import BaseModel, Char, Datetime
from pyvelm.vellum import SoftDeletes, Vellum


class DemoSoftNote(Vellum, BaseModel, SoftDeletes):
    _name = "vellum.demo.soft_note"

    title = Char(required=True)
    deleted_at = Datetime(string="Deleted At")
