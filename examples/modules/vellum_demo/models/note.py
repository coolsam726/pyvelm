from pyvelm import BaseModel, Char, Integer, One2many
from pyvelm.vellum import Vellum, on, scope


class DemoNote(Vellum, BaseModel):
    # Populated by ``_remember_created`` — used in Vellum event tests.
    _created_log: list[str] = []
    _name = "vellum.demo.note"
    _fillable = ["title", "body", "score"]

    title = Char(required=True)
    body = Char()
    score = Integer(default=0)
    comment_ids = One2many("vellum.demo.comment", inverse_name="note_id")

    @scope
    def high_score(qb):
        return qb.where("score", ">", 50)

    def get_title_upper_attribute(self) -> str:
        self.ensure_one()
        return (self.title or "").upper()

    def set_title_attribute(self, value: str) -> str:
        return (value or "").strip()

    @on("created")
    def _remember_created(self):
        self.ensure_one()
        type(self)._created_log.append(self.title)
