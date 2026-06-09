"""Odoo-style model declaration — ``from pyvelm import models``.

Use :class:`Model` for new models (``_name``) and for ``_inherit``
extensions::

    from pyvelm import Char, depends, models

    class PartnerPro(models.Model):
        _inherit = "res.partner"
        vip_note = Char()
"""
from __future__ import annotations

from .model import BaseModel


class Model(BaseModel):
    """Base class for model definitions and ``_inherit`` extensions."""

    pass


__all__ = ["Model"]
