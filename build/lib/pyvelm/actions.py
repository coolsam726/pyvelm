"""Server-action execution engine (Stage 6 Slice A).

`ir.actions.server` records represent named, storable pieces of logic
that can be invoked against a recordset at any time — from the API,
from automated-action triggers, from cron jobs, or from user-facing
buttons (future).

Four action_type values are supported:

  write   — write vals_json onto every record in the target recordset.
  create  — create one new record on model with vals_json.
  unlink  — delete every record in the target recordset.
  code    — execute a Python snippet.  Locals: env, records, action.
            The snippet may call any env/ORM method; write side effects
            are the caller's responsibility to wrap in a transaction.

Security note: `code` actions execute arbitrary Python.  They must only
be created by administrators (ACL enforced at the ORM level — Admin gets
create/write/unlink on ir.actions.server via the install hook).  Do NOT
expose `code` contents to untrusted input.
"""
from __future__ import annotations

import json

from pyvelm import BaseModel, Boolean, Char, Many2one, Text


class ServerAction(BaseModel):
    _name = "ir.actions.server"

    name = Char(required=True)
    model = Char(required=True)       # target model _name
    # One of: write / create / unlink / code
    action_type = Char(required=True)
    # JSON-encoded dict of field values used by write / create.
    vals_json = Text()
    # Python source executed for action_type == "code".
    code = Text()

    def run(self, records=None) -> None:
        """Execute this action against *records*.

        `records` should be a recordset of `self.model`.  For
        `create`-type actions the existing recordset is ignored and a
        new record is created.  Pass an empty recordset (or None) when
        the target is the model itself with no pre-selected rows.
        """
        self.ensure_one()
        env = self.env
        target_model = self.model

        if target_model not in env.registry:
            raise ValueError(
                f"ir.actions.server {self.name!r}: model {target_model!r} not in registry"
            )

        kind = self.action_type
        if kind not in ("write", "create", "unlink", "code"):
            raise ValueError(
                f"ir.actions.server {self.name!r}: unknown action_type {kind!r}"
            )

        if records is None:
            records = env[target_model]

        if kind == "write":
            if not records:
                return
            vals = json.loads(self.vals_json or "{}")
            records.write(vals)

        elif kind == "create":
            vals = json.loads(self.vals_json or "{}")
            env[target_model].create(vals)

        elif kind == "unlink":
            if not records:
                return
            records.unlink()

        elif kind == "code":
            code_src = self.code or ""
            _globals: dict = {}
            _locals: dict = {
                "env": env,
                "records": records,
                "action": self,
            }
            exec(compile(code_src, f"<action:{self.name}>", "exec"), _globals, _locals)  # noqa: S102
