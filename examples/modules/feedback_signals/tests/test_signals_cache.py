"""Tests for request-scoped analysis deduplication."""

from unittest.mock import patch

from pyvelm import Environment, Registry

from feedback_signals.signals_cache import analyze_record_once


def _fake_record(env):
    class _Rec:
        id = 42
        surface = "checkout"
        story_goal = "Pay"
        story_outcome = "Failed miserably"
        story_blocker = ""
        explicit_rating = 2

    record = _Rec()
    record.env = env
    return record


def test_analyze_record_once_deduplicates_lexicon():
    reg = Registry()
    env = Environment(None, registry=reg)  # type: ignore[arg-type]
    record = _fake_record(env)
    calls = {"n": 0}

    def _fake_lexicon(*args, **kwargs):
        calls["n"] += 1
        from feedback_signals.analysis import TextSignals

        return TextSignals(
            word_count=5,
            sentiment=-0.8,
            tone="negative",
            emotions=["frustration"],
            topics=["billing"],
            source="lexicon",
        )

    with patch(
        "feedback_signals.signals_cache.analyze_lexicon", side_effect=_fake_lexicon
    ):
        analyze_record_once(record)
        analyze_record_once(record)

    assert calls["n"] == 1


def test_analyze_record_once_uses_llm_in_background_context():
    reg = Registry()
    env = Environment(None, registry=reg).with_context(  # type: ignore[arg-type]
        feedback_signals_llm=True
    )
    record = _fake_record(env)
    calls = {"n": 0}

    def _fake_llm(*args, **kwargs):
        calls["n"] += 1
        from feedback_signals.analysis import TextSignals

        return TextSignals(
            word_count=5,
            sentiment=-0.5,
            tone="negative",
            emotions=["frustration"],
            topics=[],
            source="llm",
        )

    with patch("feedback_signals.signals_cache.analyze_text", side_effect=_fake_llm):
        analyze_record_once(record)

    assert calls["n"] == 1
