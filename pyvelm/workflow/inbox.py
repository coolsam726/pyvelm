"""Pending approvals for the current user."""
from __future__ import annotations

from typing import Any

from .engine import _user_may_act_on_approval, parse_definition


def list_inbox_items(env) -> list[dict[str, Any]]:
    """Approvals the current user can act on, newest first."""
    if "workflow.approval" not in env.registry or not env.uid:
        return []
    Approval = env["workflow.approval"]
    out: list[dict] = []
    for appr in Approval.search([("status", "=", "pending")], order="id desc"):
        if env.uid != 1 and not _user_may_act_on_approval(env, appr, env.uid):
            continue
        inst = appr.instance_id
        if not inst:
            continue
        defn = parse_definition(inst.definition_id.definition)
        tr_label = appr.transition_key
        for tr in defn.get("transitions") or []:
            if tr.get("key") == appr.transition_key:
                tr_label = tr.get("label", appr.transition_key)
                break
        state_label = inst.state
        for st in defn.get("states") or []:
            if st.get("key") == inst.state:
                state_label = st.get("label", inst.state)
                break
        record_label = f"{inst.res_model} #{inst.res_id}"
        try:
            rec = env[inst.res_model].browse(inst.res_id)
            if hasattr(rec, "display_name") and rec.display_name:
                record_label = str(rec.display_name)
        except Exception:  # noqa: BLE001
            pass
        out.append({
            "id": appr.id,
            "transition_label": tr_label,
            "state_label": state_label,
            "record_label": record_label,
            "res_model": inst.res_model,
            "res_id": inst.res_id,
            "requester": appr.requester_id.name if appr.requester_id else "",
            "deadline_at": str(appr.deadline_at) if appr.deadline_at else "",
            "form_href": _record_form_href(env, inst.res_model, inst.res_id),
        })
    return out


def _record_form_href(env, res_model: str, res_id: int) -> str | None:
    """Best-effort link to a form view for the business record."""
    if "ir.ui.view" not in env.registry:
        return None
    View = env["ir.ui.view"]
    views = View.search([
        ("model", "=", res_model),
        ("view_type", "=", "form"),
        ("active", "=", True),
    ], order="priority desc", limit=1)
    if not views:
        return None
    v = next(iter(views))
    return f"/web/views/{v.module}/{v.name}/record/{res_id}"
