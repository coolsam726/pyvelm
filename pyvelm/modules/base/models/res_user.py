"""``res.users`` — login identity and group membership."""
from __future__ import annotations

import bcrypt

from pyvelm import Boolean, Char, Many2many, Many2one, models


class Password(Char):
    """A Char that hashes its value with bcrypt on write.

    The stored column holds the bcrypt hash. Verification via
    `bcrypt.checkpw` against the hash is the only sanctioned read
    path — display code must not echo the stored value.

    Marked ``private = True`` so bulk reads and JSON serialization
    skip it by default; ``check_password()`` still reads the hash via
    the descriptor because that route doesn't consult ``private``.
    """

    private = True

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


class ResUser(models.Model):
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
    # Avatar — either an external URL or the local download path of an
    # uploaded ``ir.attachment`` (``/api/attachment/<id>/download``).
    # The image widget owns both modalities; the column itself stays a
    # plain Char so anything that links a URL just works.
    avatar_url = Char(string="Avatar")

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
