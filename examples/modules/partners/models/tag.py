from pyvelm import BaseModel, Char, Integer, Many2many


class Tag(BaseModel):
    _name = "res.tag"

    name = Char(required=True)
    # Drives the drag-reorder UI in list views that opt in via the
    # `sequence` arch key. Lower values sort first; default 10 so new
    # tags slot between common gaps.
    sequence = Integer(default=10)
    partner_ids = Many2many("res.partner")
