"""Policies for framework management models (Settings / Security / Reports)."""

from __future__ import annotations

from pyvelm.policy import BasePolicy, register_policy
from pyvelm.security import GROUP_ADMIN, user_in_group

# Models whose management UI is Admin-only (sidebar uses ``policy="view_any"``).
ADMIN_MANAGEMENT_MODELS: tuple[str, ...] = (
    "res.users",
    "res.groups",
    "res.company",
    "res.currency",
    "res.currency.rate",
    "ir.model.access",
    "ir.rule",
    "ir.actions.server",
    "base.automation",
    "ir.cron",
    "mail.message",
    "mail.template",
    "ir.report",
    "ir.report.run",
    "workflow.instance",
    "workflow.task",
)


class AdminManagementPolicy(BasePolicy):
    """Admin group may manage configuration models; others may not list them."""

    def _is_admin(self) -> bool:
        return user_in_group(self.env, GROUP_ADMIN)

    def view_any(self) -> bool:
        return self._is_admin()

    def create(self) -> bool:
        return self._is_admin()

    def view(self, record) -> bool:  # noqa: ARG002
        return self._is_admin()

    def write(self, record) -> bool:  # noqa: ARG002
        return self._is_admin()

    def unlink(self, record) -> bool:  # noqa: ARG002
        return self._is_admin()


def register_admin_policies() -> None:
    for model in ADMIN_MANAGEMENT_MODELS:
        register_policy(model, AdminManagementPolicy)
