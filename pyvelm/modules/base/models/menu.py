from pyvelm import BaseModel, Boolean, Char, Integer, Many2one, Text


class Menu(BaseModel):
    """A navigation entry contributed by an installed module.

    Identity is `(module, name)`, mirroring `ir.ui.view`. Parents are
    referenced by their `(module, name)` pair via the `parent_id`
    foreign key; module data files address parents as
    `"<module>.<name>"` and the loader resolves the ref at sync time.

    The shell renderer (:func:`pyvelm.menu.build_menu_tree`) walks this
    table to build a tree of arbitrary depth, ordered by sequence then
    label. Presentation is controlled by ``PYVELM_MENU_LAYOUT`` (see
    :mod:`pyvelm.menu`): application roots in the sidebar with children in
    the top bar (``apps``, default), or a three-level sidebar (``sidebar``).
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
    # Optional visibility gate: the entry is shown only if the user has
    # ``access_perm`` (default "read") on ``access_model``. Required for
    # custom-href entries (no view to infer a model from); view-backed
    # entries fall back to read on the view's model when unset. See
    # ``pyvelm.render._menu_node_visible``.
    access_model = Char()
    access_perm = Char()
    access_policy = Char()
