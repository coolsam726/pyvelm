"""ORM integration hooks for the workflow engine."""
from __future__ import annotations


def maybe_auto_start_workflow(env, record) -> None:
    """Start the active workflow on *record* when ``auto_start`` is set."""
    if env._acl_bypass:
        return
    if "workflow.definition" not in env.registry:
        return
    try:
        from .engine import WorkflowEngine, parse_definition

        defn_rec = WorkflowEngine.active_definition(env, record._name)
        if defn_rec is None:
            return
        defn = parse_definition(defn_rec.definition)
        if not defn.get("auto_start"):
            return
        if WorkflowEngine.instance_for_record(env, record._name, record.id):
            return
        WorkflowEngine.start(env, record, defn_rec)
    except Exception:  # noqa: BLE001
        pass
