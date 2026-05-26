"""Built-in authorization policies.

Register via :func:`register_builtin_policies` during module load so
sidebar menus, catalog gates, and :meth:`~pyvelm.env.Environment.can`
share the same rules.
"""

from .management import AdminManagementPolicy, register_admin_policies
from .workflow import (
    WorkflowApprovalPolicy,
    WorkflowDefinitionPolicy,
    register_workflow_policies,
)

__all__ = [
    "AdminManagementPolicy",
    "WorkflowApprovalPolicy",
    "WorkflowDefinitionPolicy",
    "register_admin_policies",
    "register_builtin_policies",
    "register_workflow_policies",
]


def register_builtin_policies() -> None:
    """Idempotent registration of framework policies (safe on every boot)."""
    register_admin_policies()
    register_workflow_policies()
