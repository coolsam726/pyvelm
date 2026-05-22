from pyvelm import BaseModel, Char, Many2one
from pyvelm.vellum import Vellum


class DemoComment(Vellum, BaseModel):
    _name = "vellum.demo.comment"

    note_id = Many2one("vellum.demo.note", required=True, ondelete="CASCADE")
    body = Char()
