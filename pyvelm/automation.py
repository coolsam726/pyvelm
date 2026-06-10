"""Automated-action engine and backward-compatible model re-export."""
from __future__ import annotations

from pyvelm._bundled_path import ensure_builtin_modules_path

ensure_builtin_modules_path()
from base.models.base_automation import (  # noqa: E402
    TRIGGERS,
    AutomatedAction,
)


class AutomationEngine:
    """Stateless helper — all state lives in the DB via base.automation."""

    @staticmethod
    def fire(env, model_name: str, event: str, records) -> None:
        """Run all active automation rules for (model_name, event)."""
        if "base.automation" not in env.registry:
            return
        if env._acl_bypass:
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


__all__ = ["TRIGGERS", "AutomatedAction", "AutomationEngine"]
