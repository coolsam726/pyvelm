from pyvelm import Boolean, Char, Many2one, Text, models


class IrRule(models.Model):
    _name = "ir.rule"

    name = Char(required=True)
    model = Char(required=True)
    group_id = Many2one("res.groups")       # None = global rule
    perm_read = Boolean(default=True)
    perm_write = Boolean(default=True)
    perm_create = Boolean(default=True)
    perm_unlink = Boolean(default=True)
    # JSON-encoded list of domain leaves; placeholder dicts like
    # {"placeholder": "uid"} get substituted at query time.
    domain = Text(required=True)
