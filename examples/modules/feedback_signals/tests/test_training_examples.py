"""Tests for human-verified few-shot examples."""

from feedback_signals.training_examples import (
    export_training_record,
    format_few_shot_block,
    verified_labels,
)


class _Rec:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_verified_labels_prefers_human_fields():
    rec = _Rec(
        tone_label="positive",
        emotion_tags="delight",
        topic_hints="onboarding",
        insight_summary="Auto",
        text_sentiment=0.5,
        verified_tone="negative",
        verified_emotions="frustration",
        verified_topics="billing",
        verified_insight="Human insight",
        verified_sentiment=-0.7,
    )
    gold = verified_labels(rec)
    assert gold["tone"] == "negative"
    assert gold["emotions"] == ["frustration"]
    assert gold["topics"] == ["billing"]
    assert gold["insight_summary"] == "Human insight"
    assert gold["sentiment"] == -0.7


def test_format_few_shot_block_includes_json():
    rec = _Rec(
        id=1,
        surface="checkout",
        story_goal="Pay",
        story_outcome="Failed",
        story_blocker=None,
        explicit_rating=2,
        tone_label="negative",
        emotion_tags="frustration",
        topic_hints="billing",
        insight_summary="Bad checkout",
        text_sentiment=-0.6,
        verified_tone="negative",
        verified_emotions="frustration",
        verified_topics="billing",
        verified_insight="Checkout broke trust",
        verified_sentiment=-0.65,
    )
    block = format_few_shot_block([rec])
    assert "Calibrated examples" in block
    assert '"tone": "negative"' in block
    assert "checkout" in block.lower()


def test_export_training_record():
    rec = _Rec(
        id=9,
        surface="settings",
        story_goal="Export",
        story_outcome="OK",
        story_blocker=None,
        explicit_rating=None,
        tone_label="neutral",
        emotion_tags="",
        topic_hints="",
        insight_summary="Fine",
        text_sentiment=0.1,
        analysis_source="lexicon",
        verified_tone="neutral",
        verified_emotions="",
        verified_topics="",
        verified_insight="Fine",
        verified_sentiment=0.1,
        verified_notes=None,
    )
    row = export_training_record(rec)
    assert row["id"] == 9
    assert row["labels"]["tone"] == "neutral"
