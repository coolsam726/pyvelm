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

from pyvelm import BaseModel, Boolean, Char, Many2one


# Valid trigger names.
TRIGGERS = frozenset({"on_create", "on_write", "on_unlink"})


class AutomatedAction(BaseModel):
    _name = "base.automation"

    name = Char(required=True)
    model = Char(required=True)         # model _name this rule watches
    trigger = Char(required=True)       # on_create / on_write / on_unlink
    action_id = Many2one("ir.actions.server", ondelete="CASCADE")
    active = Boolean(default=True)


class AutomationEngine:
    """Stateless helper — all state lives in the DB via base.automation."""

    @staticmethod
    def fire(env, model_name: str, event: str, records) -> None:
        """Run all active automation rules for (model_name, event).

        Failures in individual actions are logged to stderr and do NOT
        abort the calling ORM operation; automation side effects are
        best-effort unless the action itself raises inside a transaction
        that the caller manages.
        """
        if "base.automation" not in env.registry:
            return
        if env._acl_bypass:
            # Avoid recursive triggers while installing / migrating.
            return

        prev = env._acl_bypass
        env._acl_bypass = True
        try:
            rules = env["base.automation"].search([
                ("model", "=", model_name),
                ("trigger", "=", event),
                ("active", "=", True),
            ])
            for rule in rules:
                if not rule.action_id:
                    continue
                action = env["ir.actions.server"].browse(rule.action_id.id)
                try:
                    action.run(records if event != "on_create" else records)
                except Exception as exc:  # noqa: BLE001
                    import sys
                    print(
                        f"[automation] {rule.name!r} failed on {model_name}"
                        f" ({event}): {exc}",
                        file=sys.stderr,
                    )
        finally:
            env._acl_bypass = prev
