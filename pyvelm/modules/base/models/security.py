"""Access control schema: groups, users, model-access grants, record rules.

Lives in the base module so every other module can depend on these
models. The loader's install hook seeds an Admin group + uid=1
superuser; the smoke test exercises authenticated and anonymous flows
against this baseline.

Design choices:
  - Passwords are bcrypt-hashed on assignment. The `password` field
    accepts a plaintext on write and stores the hash; reads return
    the hash (callers should not display it).
  - `ir.model.access.group_id == None` means "applies to everyone,
    including unauthenticated requests." Same convention as Odoo.
  - `ir.rule.domain` is JSON-encoded; placeholder dicts like
    `{"placeholder": "uid"}` are substituted with `env.uid` at
    query time.
  - Superuser (uid=1) bypasses both ir.model.access and ir.rule.
"""
from __future__ import annotations

import bcrypt

from pyvelm import (
    BaseModel,
    Boolean,
    Char,
    Field,
    Many2many,
    Many2one,
    Text,
)


class Group(BaseModel):
    _name = "res.groups"

    name = Char(required=True)
    user_ids = Many2many("res.users")


class Password(Char):
    """A Char that hashes its value with bcrypt on write.

    The stored column holds the bcrypt hash. Verification via
    `bcrypt.checkpw` against the hash is the only sanctioned read
    path — display code must not echo the stored value.
    """

    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if not isinstance(value, str):
            raise TypeError(
                f"Password {self.name!r}: expected str, got {type(value).__name__}"
            )
        # Detect already-hashed input (bcrypt hashes start with $2 and
        # are 60 chars). Tests sometimes round-trip; treat such values
        # as already-hashed to keep the call idempotent.
        if value.startswith("$2") and len(value) == 60:
            return value
        return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


class User(BaseModel):
    _name = "res.users"
    # NOT `_company_scoped`. Users carry a `company_id` (their default
    # company at login) but stay globally visible — an admin in one
    # company should be able to manage users in any other from the same
    # screen. Setting `_company_scoped = True` here was the original
    # design but it hid cross-company users from the admin UI.

    name = Char(required=True)
    login = Char(required=True)
    password = Password()
    active = Boolean(default=True)
    group_ids = Many2many("res.groups")
    session_token = Char()
    company_id = Many2one("res.company", ondelete="SET NULL")

    def check_password(self, plaintext: str) -> bool:
        """Verify a plaintext attempt against the stored hash."""
        self.ensure_one()
        stored = self.password
        if not stored:
            return False
        try:
            return bcrypt.checkpw(plaintext.encode("utf-8"), stored.encode("ascii"))
        except (ValueError, TypeError):
            return False


class ModelAccess(BaseModel):
    _name = "ir.model.access"

    name = Char(required=True)              # human-readable label
    model = Char(required=True)             # target model `_name`
    group_id = Many2one("res.groups")       # None = applies to everyone
    perm_read = Boolean(default=False)
    perm_write = Boolean(default=False)
    perm_create = Boolean(default=False)
    perm_unlink = Boolean(default=False)


class Rule(BaseModel):
    _name = "ir.rule"

    name = Char(required=True)
    model = Char(required=True)
    group_id = Many2one("res.groups")       # None = global rule
    perm_read = Boolean(default=True)
    perm_write = Boolean(default=True)
    perm_create = Boolean(default=True)
    perm_unlink = Boolean(default=True)
    # JSON-encoded list of domain leaves; placeholder dicts like
    # {"placeholder": "uid"} get substituted at query time.
    domain = Text(required=True)
