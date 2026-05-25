# Workflows

The **workflow** module adds visual approval flows and tasks on any model.

## Install

**Apps → Workflows → Install** (requires `base` and `admin`).

## Designer

**Admin → Workflows → Design workflow** (`/web/workflow/build`)

1. **Basics** — name, record type, active, **auto-start on create**
2. **States** — pipeline stages (one initial, optional final/cancelled)
3. **Transitions** — buttons, approval rules, **stage forms** (new fields or record fields)
4. **Review** — JSON summary

Approval options per transition:

| Option | Meaning |
|--------|---------|
| **Strategy: any** | One approver from the group is enough |
| **Strategy: all** | Every member of the group must approve |
| **Strategy: sequential** | Approvers act one after another |
| **Deadline (hours)** | Optional; overdue rows are processed by cron |
| **Escalate to group** | Reassign to another group when overdue (else chatter only) |

## My approvals inbox

**Admin → Workflows → My approvals** (`/web/workflow/inbox`) lists every pending
approval assigned to you (user, group, or record field). Approve or reject in
one click, or open the underlying record.

Assigned approvers also get a **workflow.task** row (see **Workflows → Tasks**).

## Runtime

On record forms with an active workflow:

- **Status bar** — states with current step highlighted
- **Start workflow** — manual start when auto-start is off
- **Transition buttons** — open a stage form when configured
- **Approve / Reject** — for pending approvals assigned to you
- **Workflow history** — vertical timeline on the form (chatter log lines with
  subtype `workflow`; pending approvals shown at the end). On large screens the
  activity column (workflow + general chatter when the model uses `MailThread`)
  sits to the right of the form; on small screens it stacks below the main fields.

## Cron

**Workflow approval escalation** runs every 15 minutes (Settings → Cron jobs).
Install/sync the workflow module to seed it.

## Examples

**Partner onboarding** (`res.partner`) — seeded by the workflow module on install.
The **partners** example module adds chatter and a **Workflow** list column when both
are installed. Create a partner → **Draft** → **Submit for approval** → approving moves
to **Approved**. Records already stuck in **Under review** can use **Mark approved**.

**Feedback intake review** (`feedback.intake`) — seeded when you install/sync
**Feedback signals** (if the workflow module is present). New intakes auto-start
in **New** → **Send for review** → admin approves → **Mark verified**.
