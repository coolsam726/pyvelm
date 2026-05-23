"""Human-verified examples for few-shot LLM prompts and training export."""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyvelm import Environment

_ALLOWED_TONES = frozenset({"positive", "negative", "neutral", "mixed"})
_ALLOWED_EMOTIONS = frozenset(
    {"frustration", "confusion", "delight", "urgency", "distrust"}
)
_ALLOWED_TOPICS = frozenset(
    {
        "performance",
        "onboarding",
        "billing",
        "support",
        "accessibility",
        "data_loss",
    }
)


def few_shot_limit() -> int:
    raw = os.environ.get("FEEDBACK_SIGNALS_FEW_SHOT", "3").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 3


def _parse_csv_labels(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace(";", ",").split(","):
        label = part.strip().lower().replace(" ", "_")
        if label and label not in out:
            out.append(label)
    return out


def verified_labels(record) -> dict[str, Any]:
    """Gold labels for a verified intake (falls back to auto signals)."""
    tone = (record.verified_tone or record.tone_label or "neutral").strip().lower()
    if tone not in _ALLOWED_TONES:
        tone = "neutral"
    emotions = _parse_csv_labels(record.verified_emotions or record.emotion_tags)
    emotions = [e for e in emotions if e in _ALLOWED_EMOTIONS][:3]
    topics = _parse_csv_labels(record.verified_topics or record.topic_hints)
    topics = [t for t in topics if t in _ALLOWED_TOPICS][:3]
    insight = (
        (record.verified_insight or record.insight_summary or "").strip()[:240]
    )
    sentiment = record.verified_sentiment
    if sentiment is None:
        sentiment = record.text_sentiment
    try:
        sentiment = max(-1.0, min(1.0, round(float(sentiment), 3)))
    except (TypeError, ValueError):
        sentiment = 0.0
    return {
        "sentiment": sentiment,
        "tone": tone,
        "emotions": emotions,
        "topics": topics,
        "insight_summary": insight,
    }


def fetch_verified_examples(
    env: "Environment",
    *,
    surface: str | None = None,
    limit: int | None = None,
    exclude_id: int | None = None,
) -> list:
    """Recent human-verified intakes, preferring the same *surface*."""
    cap = few_shot_limit() if limit is None else max(0, limit)
    if cap <= 0:
        return []
    Intake = env["feedback.intake"]
    base = [("signals_verified", "=", True), ("active", "=", True)]
    if exclude_id:
        base.append(("id", "!=", exclude_id))

    picked: list = []
    if surface:
        picked.extend(
            Intake.search(base + [("surface", "=", surface)], limit=cap, order="id desc")
        )
    if len(picked) < cap:
        extra = cap - len(picked)
        domain = list(base)
        if picked:
            domain.append(("id", "not in", [r.id for r in picked]))
        picked.extend(Intake.search(domain, limit=extra, order="id desc"))
    return picked


def example_story_lines(record) -> list[str]:
    lines = [
        f"Surface: {record.surface or 'unknown'}",
        f"Goal: {record.story_goal or '(empty)'}",
        f"Outcome: {record.story_outcome or '(empty)'}",
    ]
    if record.story_blocker:
        lines.append(f"Blocker: {record.story_blocker}")
    if record.explicit_rating:
        lines.append(f"Stars: {record.explicit_rating}")
    return lines


def format_few_shot_block(examples: list) -> str:
    if not examples:
        return ""
    parts = [
        "",
        "Calibrated examples (human-verified — match this style and rigor):",
    ]
    for idx, rec in enumerate(examples, start=1):
        gold = verified_labels(rec)
        parts.append(f"\nExample {idx}:")
        parts.extend(example_story_lines(rec))
        parts.append("Correct JSON classification:")
        parts.append(json.dumps(gold, ensure_ascii=False))
    parts.append("")
    return "\n".join(parts)


def load_few_shot_block(
    env: "Environment",
    *,
    surface: str | None = None,
    exclude_id: int | None = None,
) -> str:
    examples = fetch_verified_examples(
        env, surface=surface, exclude_id=exclude_id
    )
    return format_few_shot_block(examples)


def export_training_record(record) -> dict[str, Any]:
    """One JSONL-ready row for offline fine-tuning."""
    labels = verified_labels(record)
    return {
        "id": record.id,
        "surface": record.surface,
        "story_goal": record.story_goal,
        "story_outcome": record.story_outcome,
        "story_blocker": record.story_blocker,
        "explicit_rating": record.explicit_rating,
        "labels": labels,
        "auto_tone": record.tone_label,
        "auto_emotions": record.emotion_tags,
        "analysis_source": record.analysis_source,
        "verified_notes": record.verified_notes,
    }
