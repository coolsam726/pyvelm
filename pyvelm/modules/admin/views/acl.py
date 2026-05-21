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
              fields=["name", field("active", widget="toggle")]),

    form_view("company.form", "res.company",
              sections=[
                  section("main", "Company", [
                      "name",
                      field("active", widget="toggle"),
                  ]),
              ]),
]
