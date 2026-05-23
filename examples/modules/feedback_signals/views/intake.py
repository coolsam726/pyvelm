"""Views for feedback.intake — story, signals, and analytics."""

from pyvelm.builders import field, form_view, graph_view, list_view, pivot_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "feedback_intake.list",
        "feedback.intake",
        title="Feedback intakes",
        create_href="/web/feedback_signals/capture",
        fields=[
            "surface",
            "insight_summary",
            "sentiment_readout",
            "mood_noise_readout",
            "confidence_readout",
            "tone_label",
            "analysis_source",
            field("signals_verified", widget="toggle"),
            "incident_date",
            field("follow_up_at", visible=False),
            "explicit_rating",
            field("emotion_tags", visible=False),
            field("topic_hints", visible=False),
            field("created_at", visible=False),
        ],
        form_view="feedback_intake.form",
    ),
    form_view(
        "feedback_intake.form",
        "feedback.intake",
        sections=[
            section(
                "story",
                "Tell us what happened",
                [
                    "surface",
                    "story_goal",
                    "story_outcome",
                    "story_blocker",
                ],
            ),
            section(
                "judgment",
                "Optional rating",
                ["explicit_rating"],
            ),
            section(
                "when",
                "When (picker demo)",
                ["incident_date", "follow_up_at", "callback_time"],
            ),
            section(
                "context",
                "Behavioral context (usually silent)",
                ["effort_seconds", "edit_count", "abandoned_once", "active"],
            ),
            section(
                "signals",
                "What we heard",
                [
                    "insight_summary",
                    "analysis_source",
                    "sentiment_readout",
                    "mood_noise_readout",
                    "confidence_readout",
                    "tone_label",
                    "emotion_tags",
                    "topic_hints",
                ],
            ),
            section(
                "verification",
                "Human verification",
                [
                    "signals_verified",
                    "verified_tone",
                    "verified_emotions",
                    "verified_topics",
                    "verified_insight",
                    "verified_sentiment",
                    "verified_notes",
                ],
            ),
            section(
                "raw",
                "Raw scores (for charts & sorting)",
                [
                    "text_sentiment",
                    "mood_noise_score",
                    "signal_confidence_score",
                ],
            ),
            section("metadata", "Record info", ["created_at", "updated_at"]),
        ],
    ),
    graph_view(
        "feedback_intake.graph_tone",
        "feedback.intake",
        title="Stories by tone",
        groupby="tone_label",
        measure="__count",
        chart="pie",
    ),
    graph_view(
        "feedback_intake.graph_surface",
        "feedback.intake",
        title="Avg mood noise by surface",
        groupby="surface",
        measure="mood_noise_score:avg",
        chart="bar",
    ),
    graph_view(
        "feedback_intake.graph_sentiment",
        "feedback.intake",
        title="Avg sentiment by surface",
        groupby="surface",
        measure="text_sentiment:avg",
        chart="bar",
    ),
    pivot_view(
        "feedback_intake.pivot",
        "feedback.intake",
        title="Surface × tone",
        row_groupby=["surface"],
        col_groupby=["tone_label"],
        measures=["__count", "mood_noise_score:avg", "text_sentiment:avg"],
    ),
]
