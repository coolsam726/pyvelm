from pyvelm import BaseModel, Char


class Region(BaseModel):
    _name = "res.region"

    name = Char(required=True)
