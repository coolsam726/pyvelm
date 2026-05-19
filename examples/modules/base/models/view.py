from pyvelm import BaseModel, Char, Integer, Many2one, Text


class View(BaseModel):
    """A view is a declarative UI definition addressed by (module, name).

    A view is either a *base* (defines `arch`) or an *extension*
    (has `inherit_id` set, declares `operations` to apply to its parent).
    Resolution walks the chain in ascending `priority` order and applies
    each level's operations; the result is the arch a renderer consumes.

    The arch shape is normalized on storage: list-of-string syntax
    sugar (e.g. `"fields": ["name", "age"]`) is rewritten to
    list-of-dict-with-`name` so addressing via list-of-keys works
    uniformly.
    """

    _name = "ir.ui.view"

    module = Char(required=True)
    name = Char(required=True)
    model = Char(required=True)
    view_type = Char(required=True)
    arch = Text()                                       # nullable on extension views
    priority = Integer(default=16)                      # Odoo default
    inherit_id = Many2one("ir.ui.view", ondelete="CASCADE")
    operations = Text()                                 # JSON list of ops on extension views
