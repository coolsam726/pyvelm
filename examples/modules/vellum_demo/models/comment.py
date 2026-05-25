from pyvelm import BaseModel, depends, fields
from pyvelm.vellum import Vellum


class DemoComment(Vellum, BaseModel):
    _name = "vellum.demo.comment"
    _rec_name = "body"

    note_id = fields.Many2one("vellum.demo.note", required=True, ondelete="CASCADE")
    body = fields.Text()
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    @depends("body")
    def _compute_body_length(self):
        for record in self:
            record.body_length = len(record.body or "")

    @depends("body")
    def _compute_body_uppercase(self):
        for record in self:
            record.body_uppercase = record.body.upper() if record.body else ""
