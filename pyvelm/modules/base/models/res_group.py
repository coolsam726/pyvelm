from pyvelm import Char, Many2many, models


class ResGroup(models.Model):
    _name = "res.groups"

    name = Char(required=True)
    user_ids = Many2many("res.users")
