"""Install / sync for feedback_signals demo."""

import os
from datetime import date, datetime, time, timedelta


def _ensure_acl(env) -> None:
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    if not admin:
        return
    admin.ensure_one()
    model = "feedback.intake"
    name = f"Admin/{model}"
    if Access.search([("name", "=", name)]):
        return
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


def _seed_samples(env) -> int:
    Intake = env["feedback.intake"]
    if Intake.search([]):
        return 0
    today = date.today()
    Intake.create(
        {
            "surface": "onboarding",
            "story_goal": "Finish signup and invite my team",
            "story_outcome": "The tutorial was clear and I felt delighted",
            "explicit_rating": 5,
            "incident_date": today - timedelta(days=2),
            "follow_up_at": datetime.now().replace(microsecond=0) + timedelta(days=5),
            "callback_time": time(10, 0),
            "effort_seconds": 240,
            "edit_count": 1,
        }
    )
    Intake.create(
        {
            "surface": "checkout",
            "story_goal": "Pay for the annual plan",
            "story_outcome": "Billing page was confusing and slow, I got stuck",
            "story_blocker": "Price changed at the last step",
            "explicit_rating": 5,
            "incident_date": today - timedelta(days=1),
            "follow_up_at": datetime.now().replace(microsecond=0) + timedelta(days=2, hours=3),
            "callback_time": time(14, 30),
            "effort_seconds": 420,
            "edit_count": 4,
            "abandoned_once": True,
        }
    )
    Intake.create(
        {
            "surface": "settings",
            "story_goal": "Export my data before leaving",
            "story_outcome": "Export failed twice, support never responded, furious",
            "story_blocker": "Lost unsaved work when the tab crashed",
            "explicit_rating": 2,
            "incident_date": today - timedelta(days=5),
            "follow_up_at": datetime.now().replace(microsecond=0) + timedelta(days=1),
            "callback_time": time(16, 0),
            "effort_seconds": 900,
            "edit_count": 6,
        }
    )
    Intake.create(
        {
            "surface": "dashboard",
            "story_goal": "Check weekly metrics",
            "story_outcome": "Works fine",
            "explicit_rating": 3,
            "incident_date": today,
            "callback_time": time(9, 0),
            "effort_seconds": 30,
        }
    )
    return 4


def _backfill_picker_samples(env) -> None:
    """Set date fields on existing intakes that pre-date the picker demo."""
    Intake = env["feedback.intake"]
    today = date.today()
    for idx, rec in enumerate(Intake.search([])):
        if rec.incident_date:
            continue
        rec.write(
            {
                "incident_date": today - timedelta(days=idx + 1),
                "follow_up_at": datetime.now().replace(microsecond=0)
                + timedelta(days=idx + 2),
                "callback_time": time(10 + (idx % 6), 0),
            }
        )


def _mark_demo_verified(env) -> None:
    """One gold example so few-shot works out of the box after seed."""
    Intake = env["feedback.intake"]
    recs = Intake.search(
        [
            ("surface", "=", "checkout"),
            ("signals_verified", "=", False),
        ],
        limit=1,
    )
    if not recs:
        return
    recs.ensure_one()
    if "confusing" not in (recs.story_outcome or "").lower():
        return
    recs.write(
        {
            "signals_verified": True,
            "verified_tone": "negative",
            "verified_emotions": "frustration, confusion",
            "verified_topics": "billing",
            "verified_insight": "Checkout flow confused them; stars likely mood-driven",
            "verified_sentiment": -0.55,
            "verified_notes": "Demo gold label for few-shot",
        }
    )


def _recompute_all_signals(env) -> None:
    """Refresh stored insights after analyzer changes (idempotent)."""
    Intake = env["feedback.intake"]
    for rec in Intake.search([]):
        # Touch story fields so @depends recomputes stored signals.
        rec.write(
            {
                "story_goal": rec.story_goal,
                "story_outcome": rec.story_outcome,
                "story_blocker": rec.story_blocker,
            }
        )


def sync(env) -> None:
    _ensure_acl(env)
    created = _seed_samples(env)
    if created:
        _mark_demo_verified(env)
    else:
        _backfill_picker_samples(env)
    # Do not bulk-call OpenRouter on Sync — free tiers 429 quickly.
    # Re-save individual intakes to refresh LLM analysis, or set
    # FEEDBACK_SIGNALS_RECOMPUTE=1 for a one-off lexicon/LLM recompute.
    if os.environ.get("FEEDBACK_SIGNALS_RECOMPUTE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        _recompute_all_signals(env)


def install(env) -> None:
    sync(env)
