"""Policy registry for record-aware authorization.

Policies are an optional layer on top of model ACL (`ir.model.access`) and
record rules (`ir.rule`). They are intended for *UI gating* and *server-side
enforcement* of per-record decisions that are awkward to express as rule
domains (e.g. "can approve if I'm the assigned approver and state is review").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .env import Environment


class BasePolicy:
    """Base class for policies.

    Subclasses may implement CRUD-like methods (`view`, `write`, etc.) and/or
    custom action methods (e.g. `approve(record) -> bool`).
    """

    def __init__(self, env: "Environment", *, model_name: str) -> None:
        self.env = env
        self.model_name = model_name

    # CRUD-ish defaults. Returning None means "no opinion" (fall back to ACL).
    def view_any(self) -> bool | None:  # noqa: PLR6301
        return None

    def create(self) -> bool | None:  # noqa: PLR6301
        return None

    def view(self, record) -> bool | None:  # noqa: PLR6301
        return None

    def write(self, record) -> bool | None:  # noqa: PLR6301
        return None

    def unlink(self, record) -> bool | None:  # noqa: PLR6301
        return None


_POLICIES: dict[str, type[BasePolicy]] = {}


def register_policy(model_name: str, policy_cls: type[BasePolicy]) -> None:
    """Register *policy_cls* for *model_name* (last write wins)."""
    _POLICIES[str(model_name)] = policy_cls


def policy_for(model_name: str) -> type[BasePolicy] | None:
    return _POLICIES.get(str(model_name))


def _policy_method(policy: BasePolicy, action: str) -> Callable[..., Any] | None:
    name = str(action or "").strip()
    if not name:
        return None
    fn = getattr(policy, name, None)
    return fn if callable(fn) else None


def eval_policy(
    env: "Environment",
    *,
    model_name: str,
    action: str,
    record=None,
    **kwargs: Any,
) -> bool | None:
    """Evaluate a policy method if registered.

    Returns:
      - True/False: policy explicitly allows/denies
      - None: no policy registered or method missing/no opinion
    """
    cls = policy_for(model_name)
    if not cls:
        return None
    policy = cls(env, model_name=str(model_name))
    fn = _policy_method(policy, action)
    if not fn:
        return None
    try:
        if record is None:
            return bool(fn(**kwargs))
        return bool(fn(record, **kwargs))
    except Exception:  # noqa: BLE001
        # Policies should never crash the UI; treat errors as "deny" at the
        # check_can layer, but at eval layer we surface as a hard False.
        return False

