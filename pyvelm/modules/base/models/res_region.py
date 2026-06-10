from pyvelm import Char, models


class ResRegion(models.Model):
    _name = "res.region"

    name = Char(required=True)
