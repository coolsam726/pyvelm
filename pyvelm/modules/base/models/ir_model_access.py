from pyvelm import Boolean, Char, Many2one, models


class IrModelAccess(models.Model):
    _name = "ir.model.access"

    name = Char(required=True)              # human-readable label
    model = Char(required=True)             # target model `_name`
    group_id = Many2one("res.groups")       # None = applies to everyone
    perm_read = Boolean(default=False)
    perm_write = Boolean(default=False)
    perm_create = Boolean(default=False)
    perm_unlink = Boolean(default=False)
