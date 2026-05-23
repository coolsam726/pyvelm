"""Request-scoped cache so one save triggers at most one analysis pass.

Sync path (submit/save): lexicon only — instant, never blocks on OpenRouter.
Background path (``feedback_signals_llm`` context): may call OpenRouter once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from feedback_signals.analysis import (
    TextSignals,
    analyze_lexicon,
    analyze_text,
    build_insight,
    mood_noise,
    signal_confidence,
)

_CACHE_ATTR = "_feedback_intake_analysis_cache"


@dataclass(frozen=True)
class RecordSignals:
    signals: TextSignals
    mood_noise_score: float
    signal_confidence_score: float
    insight_summary: str


def _cache_key(record) -> tuple[Any, ...]:
    return (
        record.id,
        record.surface or "",
        record.story_goal or "",
        record.story_outcome or "",
        record.story_blocker or "",
        record.explicit_rating,
        bool(record.env.context.get("feedback_signals_llm")),
    )


def clear_analysis_cache(env) -> None:
    if hasattr(env, _CACHE_ATTR):
        delattr(env, _CACHE_ATTR)


def _cache(env) -> dict[tuple[Any, ...], RecordSignals]:
    store = getattr(env, _CACHE_ATTR, None)
    if store is None:
        store = {}
        setattr(env, _CACHE_ATTR, store)
    return store


def analyze_record_once(record) -> RecordSignals:
    """Analyze feedback for *record* at most once per env + mode (lexicon/llm)."""
    key = _cache_key(record)
    hit = _cache(record.env).get(key)
    if hit is not None:
        return hit

    use_llm = bool(record.env.context.get("feedback_signals_llm"))
    if use_llm:
        from feedback_signals.training_examples import load_few_shot_block

        few_shot = load_few_shot_block(
            record.env,
            surface=record.surface,
            exclude_id=record.id or None,
        )
        signals = analyze_text(
            record.story_goal,
            record.story_outcome,
            record.story_blocker,
            surface=record.surface,
            explicit_rating=record.explicit_rating,
            few_shot_block=few_shot,
        )
    else:
        signals = analyze_lexicon(
            record.story_goal,
            record.story_outcome,
            record.story_blocker,
        )
    filled = sum(
        1
        for v in (
            record.story_goal,
            record.story_outcome,
            record.story_blocker,
            record.explicit_rating,
        )
        if v
    )
    noise = mood_noise(
        record.explicit_rating,
        signals.sentiment,
        signals.word_count,
    )
    confidence = signal_confidence(
        signals.word_count, filled, source=signals.source
    )
    insight = signals.insight_summary or build_insight(
        tone=signals.tone,
        emotions=signals.emotions,
        topics=signals.topics,
        mood_noise_score=noise,
        sentiment=signals.sentiment,
        word_count=signals.word_count,
    )
    result = RecordSignals(
        signals=signals,
        mood_noise_score=noise,
        signal_confidence_score=confidence,
        insight_summary=insight,
    )
    _cache(record.env)[key] = result
    return result
