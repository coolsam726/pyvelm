"""Chatter + workflow display fields on partners (requires workflow module at runtime)."""
from __future__ import annotations

from pyvelm import BaseModel, Char, depends
from pyvelm.mail import MailThread


class PartnerWorkflow(MailThread, BaseModel):
    _inherit = "res.partner"

    workflow_state = Char(compute="_compute_workflow_display", string="Workflow")
    workflow_state_label = Char(compute="_compute_workflow_display", string="Workflow status")

    @depends("id")
    def _compute_workflow_display(self):
        from pyvelm.workflow.engine import WorkflowEngine, parse_definition

        for rec in self:
            rec.workflow_state = ""
            rec.workflow_state_label = ""
            if not rec.id:
                continue
            if "workflow.instance" not in self.env.registry:
                continue
            inst = WorkflowEngine.instance_for_record(self.env, rec._name, rec.id)
            if not inst:
                continue
            rec.workflow_state = inst.state or ""
            defn = parse_definition(inst.definition_id.definition)
            label = inst.state or ""
            for st in defn.get("states") or []:
                if st.get("key") == inst.state:
                    label = st.get("label", inst.state)
                    break
            rec.workflow_state_label = label
