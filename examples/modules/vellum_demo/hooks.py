"""Install / sync hooks for ``vellum_demo``.

``sync`` runs on Apps **Sync** (same version) and on first install via
``install``. Idempotent — safe to click Sync repeatedly.
"""


def _ensure_acl(env) -> None:
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    if not admin:
        return
    admin.ensure_one()
    for model in (
        "vellum.demo.note",
        "vellum.demo.comment",
        "vellum.demo.soft_note",
    ):
        name = f"Admin/{model}"
        if Access.search([("name", "=", name)]):
            continue
        Access.create(
            {
                "name": name,
                "model": model,
                "group_id": admin,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            }
        )


def _seed_demo_rows(env) -> int:
    """Create sample rows when tables are empty. Returns rows created."""
    Note = env["vellum.demo.note"]
    if Note.search([]):
        return 0
    low = Note.create({"title": "  Low score  ", "body": "Warm-up", "score": 10})
    high = Note.create(
        {"title": "High score", "body": "Vellum scope target", "score": 90}
    )
    env["vellum.demo.comment"].create(
        {"note_id": low, "body": "Comment on low note"}
    )
    env["vellum.demo.comment"].create(
        {"note_id": high, "body": "Comment on high note"}
    )
    env["vellum.demo.soft_note"].create({"title": "Soft-delete example"})
    return 4


def sync(env) -> None:
    """Apps Sync / upgrade resync — schema + views are handled by the loader."""
    _ensure_acl(env)
    _seed_demo_rows(env)


def install(env) -> None:
    sync(env)
