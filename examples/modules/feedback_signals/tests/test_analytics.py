"""Tests for signal interpretation and analytics rollups."""

from feedback_signals.analytics import gather_analytics
from feedback_signals.interpret import (
    confidence_readout,
    mood_noise_readout,
    sentiment_readout,
)


def test_sentiment_readout_bands():
    assert "negative" in sentiment_readout(-0.6).lower()
    assert "Positive" in sentiment_readout(0.5)
    assert "Neutral" in sentiment_readout(0.0)


def test_mood_noise_readout_high():
    assert "mood" in mood_noise_readout(0.7).lower()


def test_gather_analytics_empty():
    class _Empty:
        _ids = []

        def __iter__(self):
            return iter(())

    snap = gather_analytics(_Empty())
    assert snap.total == 0


def test_gather_analytics_from_records():
    class _Rec:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class _Rs:
        _ids = [1, 2]

        def __iter__(self):
            yield _Rec(
                id=1,
                analysis_source="llm",
                tone_label="negative",
                surface="checkout",
                mood_noise_score=0.7,
                text_sentiment=-0.8,
                signal_confidence_score=0.8,
                emotion_tags="frustration",
                topic_hints="billing",
                insight_summary="Frustrated at checkout",
            )
            yield _Rec(
                id=2,
                analysis_source="lexicon",
                tone_label="positive",
                surface="onboarding",
                mood_noise_score=0.1,
                text_sentiment=0.6,
                signal_confidence_score=0.5,
                emotion_tags="delight",
                topic_hints="onboarding",
                insight_summary="Happy signup",
            )

    snap = gather_analytics(_Rs())
    assert snap.total == 2
    assert snap.llm_count == 1
    assert snap.high_mood_noise == 1
    assert snap.emotions[0][0] == "frustration"
