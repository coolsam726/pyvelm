"""Custom capture UI routes for the feedback_signals demo."""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path

import jinja2
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from pyvelm import Environment
from pyvelm.render import merge_template_context, register_shell_globals

_MODULE_DIR = Path(__file__).resolve().parent
_TEMPLATES = jinja2.Environment(
    loader=jinja2.ChoiceLoader(
        [
            jinja2.FileSystemLoader(str(_MODULE_DIR / "templates")),
            jinja2.PackageLoader("pyvelm", "templates"),
        ]
    ),
    autoescape=jinja2.select_autoescape(["html"]),
)
register_shell_globals(_TEMPLATES)

_SURFACES = [
    {"id": "onboarding", "label": "Getting started", "hint": "Signup, tour, first run"},
    {"id": "checkout", "label": "Checkout", "hint": "Plans, payment, invoices"},
    {"id": "dashboard", "label": "Dashboard", "hint": "Reports, daily workflow"},
    {"id": "settings", "label": "Settings", "hint": "Account, privacy, exports"},
    {"id": "other", "label": "Somewhere else", "hint": "We'll still listen"},
]


def _render(name: str, env: Environment | None = None, **ctx) -> str:
    current_path = ctx.get("current_path")
    base = merge_template_context(env, current_path) if env is not None else {}
    base.update(ctx)
    return _TEMPLATES.get_template(name).render(**base)


def register_routes(app) -> None:
    """Mount capture page, submit handler, and static assets on *app*."""
    from feedback_signals.background_analysis import configure

    registry = app.state.registry
    pool = app.state.pool
    configure(pool, registry)

    static_dir = _MODULE_DIR / "static"
    if static_dir.is_dir():
        app.mount(
            "/web/feedback_signals/static",
            StaticFiles(directory=str(static_dir)),
            name="feedback-signals-static",
        )

    def get_env(request: Request):
        from pyvelm.request_env import apply_request_scope

        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env = apply_request_scope(
                env,
                request,
                resolve_session=_resolve_session,
                resolve_basic=_resolve_basic,
            )
            yield env

    def _auth_redirect(request: Request) -> RedirectResponse:
        next_url = str(request.url.path)
        if request.url.query:
            next_url += "?" + request.url.query
        return RedirectResponse(f"/login?next={next_url}", status_code=302)

    @app.get("/web/feedback_signals/capture", response_class=HTMLResponse)
    def capture_page(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_redirect(request)
        env.check_access("feedback.intake", "create")
        return HTMLResponse(
            _render(
                "feedback_capture.html",
                env=env,
                csrf_token=request.state.csrf_token,
                surfaces=_SURFACES,
                current_path=str(request.url.path),
                mode="capture",
                repost=None,
            )
        )

    @app.post("/web/feedback_signals/capture", response_class=HTMLResponse)
    async def capture_submit(
        request: Request,
        env: Environment = Depends(get_env),
        surface: str = Form(...),
        story_goal: str = Form(""),
        story_outcome: str = Form(""),
        story_blocker: str = Form(""),
        explicit_rating: str = Form(""),
        effort_seconds: int = Form(0),
        edit_count: int = Form(0),
        abandoned_once: str = Form("false"),
    ):
        if env.uid is None:
            return _auth_redirect(request)
        env.check_access("feedback.intake", "create")

        rating_val = None
        if explicit_rating.strip().isdigit():
            rating_val = int(explicit_rating)

        vals = {
            "surface": surface.strip()[:64] or "other",
            "story_goal": story_goal.strip() or None,
            "story_outcome": story_outcome.strip() or None,
            "story_blocker": story_blocker.strip() or None,
            "explicit_rating": rating_val,
            "effort_seconds": max(0, effort_seconds),
            "edit_count": max(0, edit_count),
            "abandoned_once": abandoned_once.lower() in ("1", "true", "yes", "on"),
            "active": True,
        }
        if not vals["story_goal"] and not vals["story_outcome"]:
            return HTMLResponse(
                _render(
                    "feedback_capture.html",
                    env=env,
                    csrf_token=request.state.csrf_token,
                    surfaces=_SURFACES,
                    current_path="/web/feedback_signals/capture",
                    mode="capture",
                    form_error="Tell us at least what you were doing or what happened.",
                    repost=vals,
                ),
                status_code=422,
            )

        with env.transaction():
            rec = env["feedback.intake"].create(vals)

        return HTMLResponse(
            _render(
                "feedback_capture.html",
                env=env,
                csrf_token=request.state.csrf_token,
                surfaces=_SURFACES,
                current_path="/web/feedback_signals/capture",
                mode="thanks",
                record=rec,
                repost=None,
            )
        )


    @app.get("/web/feedback_signals/analytics", response_class=HTMLResponse)
    def analytics_page(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_redirect(request)
        env.check_access("feedback.intake", "read")
        from feedback_signals.analytics import gather_analytics
        from feedback_signals.interpret import SIGNAL_GLOSSARY

        records = env["feedback.intake"].search([])
        snap = gather_analytics(records)
        return HTMLResponse(
            _render(
                "signal_analytics.html",
                env=env,
                snap=snap,
                glossary=SIGNAL_GLOSSARY,
                current_path=str(request.url.path),
            )
        )

    @app.get("/web/feedback_signals/review", response_class=HTMLResponse)
    def review_queue(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_redirect(request)
        env.check_access("feedback.intake", "read")
        Intake = env["feedback.intake"]
        pending = Intake.search(
            [("signals_verified", "=", False), ("active", "=", True)],
            limit=40,
            order="id desc",
        )
        verified_count = Intake.search_count([("signals_verified", "=", True)])
        return HTMLResponse(
            _render(
                "signal_review.html",
                env=env,
                pending=pending,
                pending_count=len(pending),
                verified_count=verified_count,
                current_path=str(request.url.path),
            )
        )

    @app.get("/web/feedback_signals/verify/{record_id}", response_class=HTMLResponse)
    def verify_page(
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
        saved: str = "",
    ):
        if env.uid is None:
            return _auth_redirect(request)
        env.check_access("feedback.intake", "write")
        record = _load_intake(env, record_id)
        return HTMLResponse(
            _render_verify(
                request,
                record,
                env=env,
                saved=saved == "1",
                form_error=None,
            )
        )

    @app.post("/web/feedback_signals/verify/{record_id}", response_class=HTMLResponse)
    async def verify_submit(
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
        action: str = Form("save"),
        verified_tone: str = Form("neutral"),
        verified_emotions: str = Form(""),
        verified_topics: str = Form(""),
        verified_insight: str = Form(""),
        verified_sentiment: str = Form("0"),
        verified_notes: str = Form(""),
    ):
        if env.uid is None:
            return _auth_redirect(request)
        env.check_access("feedback.intake", "write")
        record = _load_intake(env, record_id)

        if action == "approve":
            vals = {
                "signals_verified": True,
                "verified_tone": record.tone_label or "neutral",
                "verified_emotions": record.emotion_tags or "",
                "verified_topics": record.topic_hints or "",
                "verified_insight": record.insight_summary or "",
                "verified_sentiment": record.text_sentiment,
                "verified_notes": verified_notes.strip() or None,
            }
        else:
            err = _validate_verification_form(
                verified_tone=verified_tone,
                verified_sentiment=verified_sentiment,
            )
            if err:
                return HTMLResponse(
                    _render_verify(
                        request,
                        record,
                        env=env,
                        saved=False,
                        form_error=err,
                        overrides={
                            "tone": verified_tone,
                            "emotions": verified_emotions,
                            "topics": verified_topics,
                            "insight": verified_insight,
                            "sentiment": verified_sentiment,
                            "notes": verified_notes,
                        },
                    ),
                    status_code=422,
                )
            vals = {
                "signals_verified": True,
                "verified_tone": verified_tone.strip().lower(),
                "verified_emotions": verified_emotions.strip() or None,
                "verified_topics": verified_topics.strip() or None,
                "verified_insight": verified_insight.strip() or None,
                "verified_sentiment": float(verified_sentiment),
                "verified_notes": verified_notes.strip() or None,
            }

        with env.transaction():
            record.write(vals)

        return RedirectResponse(
            f"/web/feedback_signals/verify/{record_id}?saved=1",
            status_code=303,
        )

    @app.get("/web/feedback_signals/export-training.jsonl")
    def export_training(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Login required")
        env.check_access("feedback.intake", "read")
        from feedback_signals.training_examples import export_training_record

        lines: list[str] = []
        for rec in env["feedback.intake"].search(
            [("signals_verified", "=", True)], order="id asc"
        ):
            lines.append(json.dumps(export_training_record(rec), ensure_ascii=False))
        body = "\n".join(lines) + ("\n" if lines else "")
        return PlainTextResponse(
            body,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": 'attachment; filename="feedback_training.jsonl"'
            },
        )


def _load_intake(env: Environment, record_id: int):
    recs = env["feedback.intake"].search([("id", "=", record_id)], limit=1)
    if not recs:
        raise HTTPException(status_code=404, detail="Intake not found")
    recs.ensure_one()
    return recs


def _validate_verification_form(*, verified_tone: str, verified_sentiment: str) -> str | None:
    tone = verified_tone.strip().lower()
    if tone not in {"positive", "negative", "neutral", "mixed"}:
        return "Tone must be positive, negative, neutral, or mixed."
    try:
        score = float(verified_sentiment)
    except ValueError:
        return "Sentiment must be a number between -1 and 1."
    if score < -1.0 or score > 1.0:
        return "Sentiment must be between -1 and 1."
    return None


def _render_verify(
    request: Request,
    record,
    env: Environment,
    *,
    saved: bool,
    form_error: str | None,
    overrides: dict | None = None,
) -> str:
    from feedback_signals.training_examples import verified_labels

    if overrides:
        defaults = {
            "tone": overrides.get("tone", "neutral"),
            "sentiment": overrides.get("sentiment", "0"),
            "emotions": overrides.get("emotions", ""),
            "topics": overrides.get("topics", ""),
            "insight": overrides.get("insight", ""),
        }
    elif record.signals_verified:
        gold = verified_labels(record)
        defaults = {
            "tone": gold["tone"],
            "sentiment": gold["sentiment"],
            "emotions": ", ".join(gold["emotions"]),
            "topics": ", ".join(gold["topics"]),
            "insight": gold["insight_summary"],
        }
    else:
        defaults = {
            "tone": record.tone_label or "neutral",
            "sentiment": record.text_sentiment if record.text_sentiment is not None else 0,
            "emotions": record.emotion_tags or "",
            "topics": record.topic_hints or "",
            "insight": record.insight_summary or "",
        }
    return _render(
        "signal_verify.html",
        env=env,
        csrf_token=request.state.csrf_token,
        record=record,
        defaults=defaults,
        saved=saved,
        form_error=form_error,
        tone_choices=["positive", "negative", "neutral", "mixed"],
        emotion_hint="frustration, confusion, delight, urgency, distrust",
        topic_hint="performance, onboarding, billing, support, accessibility, data_loss",
        current_path=str(request.url.path),
    )


def _resolve_session(env: Environment, token: str | None) -> int | None:
    if not token or "res.users" not in env.registry:
        return None
    env._acl_bypass = True
    try:
        users = env["res.users"].search(
            [("session_token", "=", token), ("active", "=", True)], limit=1
        )
        if not users:
            return None
        users.ensure_one()
        return users.id
    finally:
        env._acl_bypass = False


def _resolve_basic(env: Environment, header_value: str | None) -> int | None:
    if not header_value or not header_value.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header_value.split(None, 1)[1])
        login, password = raw.decode("utf-8", errors="ignore").split(":", 1)
    except (binascii.Error, ValueError):
        return None
    if "res.users" not in env.registry:
        return None
    env._acl_bypass = True
    try:
        users = env["res.users"].search(
            [("login", "=", login), ("active", "=", True)], limit=1
        )
        if not users:
            return None
        users.ensure_one()
        if not users.check_password(password):
            return None
        return users.id
    finally:
        env._acl_bypass = False
