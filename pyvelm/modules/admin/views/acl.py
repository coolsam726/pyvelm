"""View declarations for the admin module.

Provides list + form views for the four ACL models that live in base:
  - res.groups       (groups)
  - res.users        (users)
  - ir.model.access  (access control entries)
  - ir.rule          (record rules / row-level security)

These are just regular pyvelm views — the admin module ships no custom
Python models; it reuses the ones defined in base.
"""

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    # ---- res.groups ----
    list_view("group.list", "res.groups",
              fields=["name"]),

    form_view("group.form", "res.groups",
              sections=[
                  section("main",    "Group",   ["name"]),
                  section("members", "Members", ["user_ids"]),
              ]),

    # ---- res.users ----
    list_view("user.list", "res.users",
              fields=["name", "login", field("active", widget="toggle")]),

    form_view("user.form", "res.users",
              sections=[
                  section("identity", "Identity", [
                      "name", "login", "password",
                      field("active", widget="toggle"),
                  ]),
                  section("groups", "Groups", ["group_ids"]),
              ]),

    # ---- ir.model.access ----
    list_view("access.list", "ir.model.access",
              title="Model Access",
              fields=[
                  "name", "model", "group_id",
                  field("perm_read",   widget="toggle"),
                  field("perm_write",  widget="toggle"),
                  field("perm_create", widget="toggle"),
                  field("perm_unlink", widget="toggle"),
              ]),

    form_view("access.form", "ir.model.access",
              sections=[
                  section("main",        "Access Rule",  ["name", "model", "group_id"]),
                  section("permissions", "Permissions", [
                      field("perm_read",   widget="toggle"),
                      field("perm_write",  widget="toggle"),
                      field("perm_create", widget="toggle"),
                      field("perm_unlink", widget="toggle"),
                  ]),
              ]),

    # ---- ir.rule ----
    list_view("rule.list", "ir.rule",
              fields=[
                  "name", "model", "group_id",
                  field("perm_read",   widget="toggle"),
                  field("perm_write",  widget="toggle"),
                  field("perm_create", widget="toggle"),
                  field("perm_unlink", widget="toggle"),
              ]),

    form_view("rule.form", "ir.rule",
              sections=[
                  section("main",        "Record Rule", ["name", "model", "group_id", "domain"]),
                  section("permissions", "Applies On",  [
                      field("perm_read",   widget="toggle"),
                      field("perm_write",  widget="toggle"),
                      field("perm_create", widget="toggle"),
                      field("perm_unlink", widget="toggle"),
                  ]),
              ]),

    # ---- res.company ----
    list_view("company.list", "res.company",
              fields=["name", "currency_id", "timezone",
                      field("active", widget="toggle")]),

    form_view("company.form", "res.company",
              sections=[
                  section("main", "Company", [
                      "name",
                      "currency_id",
                      "timezone",
                      field("active", widget="toggle"),
                  ]),
              ]),

    # ---- res.currency ----
    list_view("currency.list", "res.currency",
              fields=["code", "name", "symbol", "rounding",
                      field("active", widget="toggle")]),

    form_view("currency.form", "res.currency",
              sections=[
                  section("main", "Currency", [
                      "code",
                      "name",
                      "symbol",
                      "rounding",
                      field("active", widget="toggle"),
                  ]),
                  section("rates", "Exchange rates",
                          [field("rate_ids", widget="table")]),
              ]),

    # ---- res.currency.rate ----
    list_view("currency.rate.list", "res.currency.rate",
              fields=["currency_id", "date", "rate"]),

    form_view("currency.rate.form", "res.currency.rate",
              sections=[
                  section("main", "Rate", ["currency_id", "date", "rate"]),
              ]),

    # ---- ir.actions.server ----
    list_view("action.list", "ir.actions.server",
              title="Server Actions",
              fields=["name", "model", "action_type"]),

    form_view("action.form", "ir.actions.server",
              sections=[
                  section("main", "Action",
                          ["name", "model", "action_type"]),
                  section("payload", "Payload",
                          ["vals_json", "code"]),
              ]),

    # ---- base.automation ----
    list_view("automation.list", "base.automation",
              title="Automation Rules",
              fields=["name", "model", "trigger", "action_id",
                      field("active", widget="toggle")]),

    form_view("automation.form", "base.automation",
              sections=[
                  section("main", "Automation", [
                      "name", "model", "trigger", "action_id",
                      field("active", widget="toggle"),
                  ]),
              ]),

    # ---- ir.cron ----
    list_view("cron.list", "ir.cron",
              title="Scheduled Jobs",
              fields=["name", "action_id", "interval_number",
                      "interval_type", "lastcall", "nextcall",
                      field("active", widget="toggle")]),

    form_view("cron.form", "ir.cron",
              header_actions=[
                  {
                      "label": "Run Now",
                      "url": "/web/cron/{id}/run-now",
                      "method": "POST",
                      "confirm": "Run this job now?",
                  },
              ],
              sections=[
                  section("main", "Job",
                          ["name", "action_id",
                           field("active", widget="toggle")]),
                  section("schedule", "Schedule",
                          ["interval_number", "interval_type",
                           "nextcall", "lastcall"]),
              ]),

    # ---- mail.message ----
    list_view("message.list", "mail.message",
              title="Messages",
              fields=["date", "subject", "recipient_email",
                      "state", "message_type"]),

    form_view("message.form", "mail.message",
              sections=[
                  section("main", "Message", [
                      "subject", "recipient_email", "date",
                      "message_type", "state",
                  ]),
                  section("body", "Body", ["body"]),
                  section("meta", "Meta", [
                      "model", "res_id", "author_id", "subtype", "error",
                  ]),
              ]),
]
