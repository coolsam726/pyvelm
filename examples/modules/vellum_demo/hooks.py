"""Install / sync hooks for ``vellum_demo``.

``sync`` runs on Apps **Sync** (same version) and on first install via
``install``. Idempotent — safe to click Sync repeatedly.
"""
from datetime import date, datetime, time, timedelta


def _ensure_acl(env) -> None:
    from pyvelm.security import grant_model_access

    for model in (
        "vellum.demo.note",
        "vellum.demo.comment",
        "vellum.demo.soft_note",
    ):
        grant_model_access(env, model, admin="crud", user="read")


def _seed_demo_rows(env) -> int:
    """Create sample rows when tables are empty. Returns rows created."""
    Note = env["vellum.demo.note"]
    if Note.search([]):
        return 0
    today = date.today()
    low = Note.create(
        {
            "title": "  Low score  ",
            "body": "Warm-up",
            "score": 10,
            "publish_on": today + timedelta(days=7),
            "event_at": datetime.now().replace(microsecond=0) + timedelta(days=3),
            "standup_at": time(9, 30),
        }
    )
    high = Note.create(
        {
            "title": "High score",
            "body": "Vellum scope target",
            "score": 90,
            "publish_on": today,
            "event_at": datetime.now().replace(microsecond=0) + timedelta(days=14),
            "standup_at": time(11, 0),
        }
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
