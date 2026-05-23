from pyvelm import BaseModel, fields
from pyvelm.vellum import QueryBuilder, Vellum, on, scope


class DemoNote(Vellum, BaseModel):
    # Populated by ``_remember_created`` — used in Vellum event tests.
    _created_log: list[str] = []
    _name = "vellum.demo.note"
    _rec_name = "title"

    title = fields.Char(required=True)
    body = fields.Char()
    score = fields.Integer(default=0)
    publish_on = fields.Date(string="Publish on")
    event_at = fields.Datetime(string="Event at")
    standup_at = fields.Time(string="Daily standup")
    comment_ids = fields.One2many("vellum.demo.comment", inverse_name="note_id")
    active = fields.Boolean(default=True)

    @scope
    def high_score(qb: QueryBuilder) -> QueryBuilder:
        """Notes with score above 50."""
        return qb.where("score", ">", 50)

    def get_title_upper_attribute(self) -> str:
        """Vellum accessor for ``title_upper`` (uppercase title)."""
        self.ensure_one()
        return (self.title or "").upper()

    def set_title_attribute(self, value: str) -> str:
        """Vellum mutator: strip whitespace before persisting ``title``."""
        return (value or "").strip()

    @on("created")
    def _remember_created(self):
        """Append this note's title to ``_created_log`` (event hook demo)."""
        self.ensure_one()
        type(self)._created_log.append(self.title)
