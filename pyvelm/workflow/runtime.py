"""ORM integration hooks for the workflow engine."""
from __future__ import annotations


def _workflow_schema_ready(env) -> bool:
    """True when workflow runtime tables exist (module installed)."""
    if "workflow.definition" not in env.registry:
        return False
    cls = env.registry["workflow.definition"]
    row = env.conn.execute(
        "SELECT to_regclass(%s)", [cls._table]
    ).fetchone()
    return bool(row and row[0])


def maybe_auto_start_workflow(env, record) -> None:
    """Start the active workflow on *record* when ``auto_start`` is set."""
    if env._acl_bypass:
        return
    if not _workflow_schema_ready(env):
        return
    try:
        # Savepoint: a failed lookup/start must not abort the caller's
        # outer transaction (e.g. base install before workflow tables exist).
        with env.transaction():
            _maybe_auto_start_workflow_inner(env, record)
    except Exception:  # noqa: BLE001
        pass


def _maybe_auto_start_workflow_inner(env, record) -> None:
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
