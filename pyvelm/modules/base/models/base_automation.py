"""Automated-action trigger engine (Stage 6 Slice B).

`base.automation` records attach a server action to a model-level ORM
event.  The three supported trigger values are:

  on_create  — fires after every successful create() on the model.
  on_write   — fires after every successful write() on the model.
  on_unlink  — fires before every unlink() on the model.

The ORM calls `AutomationEngine.fire(env, model_name, event, records)`
from within `BaseModel.create / write / unlink`.  The call is a no-op
if `base.automation` is not in the registry (e.g. during early install).

`base.automation` records are active (active=True) by default.
Deactivating a rule suppresses it without deleting it.
"""
from __future__ import annotations

from pyvelm import Boolean, Char, Many2one, models


# Valid trigger names.
TRIGGERS = frozenset({"on_create", "on_write", "on_unlink"})


class AutomatedAction(models.Model):
    _name = "base.automation"

    name = Char(required=True)
    model = Char(required=True)         # model _name this rule watches
    trigger = Char(required=True)       # on_create / on_write / on_unlink
    action_id = Many2one("ir.actions.server", ondelete="CASCADE")
    active = Boolean(default=True)


