from pyvelm import BaseModel, Boolean, Char, Integer, Many2one, Text


class Menu(BaseModel):
    """A navigation entry contributed by an installed module.

    Identity is `(module, name)`, mirroring `ir.ui.view`. Parents are
    referenced by their `(module, name)` pair via the `parent_id`
    foreign key; module data files address parents as
    `"<module>.<name>"` and the loader resolves the ref at sync time.

    The sidebar renderer (`pyvelm.render._menu`) walks this table to
    build a two-level tree: top-level entries (parent_id NULL) and
    their direct children, ordered by sequence then label.
    """

    _name = "ir.ui.menu"

    module = Char(required=True)
    name = Char(required=True)
    label = Char(required=True)
    parent_id = Many2one("ir.ui.menu", ondelete="CASCADE")
    sequence = Integer(default=10)
    href = Char()                                       # nullable on group entries
    icon = Text()                                       # raw SVG markup, nullable
    active = Boolean(default=True)
