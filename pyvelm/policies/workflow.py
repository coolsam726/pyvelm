"""Workflow-specific policies (inbox vs admin lists)."""

from __future__ import annotations

from pyvelm.policy import BasePolicy, register_policy
from pyvelm.security import GROUP_ADMIN, user_in_group


class WorkflowDefinitionPolicy(BasePolicy):
    """Design-time workflow definitions — Admin only."""

    def _is_admin(self) -> bool:
        return user_in_group(self.env, GROUP_ADMIN)

    def view_any(self) -> bool:
        return self._is_admin()

    def design(self) -> bool:
        return self._is_admin()

    def create(self) -> bool:
        return self._is_admin()


class WorkflowApprovalPolicy(BasePolicy):
    """Admin approval lists vs operator inbox."""

    def view_any(self) -> bool:
        return user_in_group(self.env, GROUP_ADMIN)

    def inbox(self) -> bool:
        # ACL ceiling (``perm="read"`` on the menu) already applied; any user
        # granted read may open the inbox (typically internal User group).
        return True


def register_workflow_policies() -> None:
    register_policy("workflow.definition", WorkflowDefinitionPolicy)
    register_policy("workflow.approval", WorkflowApprovalPolicy)
