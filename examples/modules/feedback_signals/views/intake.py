"""Views for feedback.intake — story, signals, and analytics."""

from pyvelm.builders import (
    Field,
    FormView,
    GraphView,
    ListView,
    PivotView,
    ViewsData,
)

views_data = (
    ViewsData.make()
    .views(
        ListView.make("feedback_intake.list")
        .model("feedback.intake")
        .title("Feedback intakes")
        .create_href("/web/feedback_signals/capture")
        .columns(
            [
                "surface",
                "insight_summary",
                "sentiment_readout",
                "mood_noise_readout",
                "confidence_readout",
                "tone_label",
                "analysis_source",
                Field.make("signals_verified").toggle(),
                "incident_date",
                Field.make("follow_up_at").set(visible=False),
                "explicit_rating",
                Field.make("emotion_tags").set(visible=False),
                Field.make("topic_hints").set(visible=False),
                Field.make("created_at").set(visible=False),
            ]
        )
        .form_view("feedback_intake.form"),
        FormView.make("feedback_intake.form")
        .model("feedback.intake")
        .section(
            "story",
            "Tell us what happened",
            [
                "surface",
                "story_goal",
                "story_outcome",
                "story_blocker",
            ],
        )
        .section(
            "judgment",
            "Optional rating",
            ["explicit_rating"],
        )
        .section(
            "when",
            "When (picker demo)",
            ["incident_date", "follow_up_at", "callback_time"],
        )
        .section(
            "context",
            "Behavioral context (usually silent)",
            ["effort_seconds", "edit_count", "abandoned_once", "active"],
        )
        .section(
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
        )
        .section(
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
        )
        .section(
            "raw",
            "Raw scores (for charts & sorting)",
            [
                "text_sentiment",
                "mood_noise_score",
                "signal_confidence_score",
            ],
        )
        .section("metadata", "Record info", ["created_at", "updated_at"]),
        GraphView.make("feedback_intake.graph_tone")
        .model("feedback.intake")
        .title("Stories by tone")
        .groupby("tone_label")
        .measure("__count")
        .chart("pie"),
        GraphView.make("feedback_intake.graph_surface")
        .model("feedback.intake")
        .title("Avg mood noise by surface")
        .groupby("surface")
        .measure("mood_noise_score:avg")
        .chart("bar"),
        GraphView.make("feedback_intake.graph_sentiment")
        .model("feedback.intake")
        .title("Avg sentiment by surface")
        .groupby("surface")
        .measure("text_sentiment:avg")
        .chart("bar"),
        PivotView.make("feedback_intake.pivot")
        .model("feedback.intake")
        .title("Surface × tone")
        .row_groupby(["surface"])
        .col_groupby(["tone_label"])
        .measures(["__count", "mood_noise_score:avg", "text_sentiment:avg"]),
    )
)
