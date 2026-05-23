"""Narrative-first feedback with derived signals (demo)."""

from typing import Any

from pyvelm import BaseModel, Boolean, Char, Date, Datetime, Float, Integer, Text, Time, depends

from feedback_signals.background_analysis import (
    schedule_llm_analysis,
    story_fields_changed,
)
from feedback_signals.interpret import (
    confidence_readout,
    mood_noise_readout,
    sentiment_readout,
)
from feedback_signals.signals_cache import analyze_record_once


class FeedbackIntake(BaseModel):
    """One feedback moment: story first, optional rating, computed insight."""

    _name = "feedback.intake"
    _rec_name = "surface"

    # --- Capture: narrative before judgment ---------------------------------
    surface = Char(required=True, string="Where")
    story_goal = Text(string="What were you trying to do?")
    story_outcome = Text(string="What happened?")
    story_blocker = Text(string="What got in the way? (optional)")
    explicit_rating = Integer(string="Stars (optional)")

    # --- When (Flowbite date / datetime / time widgets on admin form) -----
    incident_date = Date(string="Incident date")
    follow_up_at = Datetime(string="Follow-up call")
    callback_time = Time(string="Callback window")

    # --- Behavioral context (normally collected silently) -------------------
    effort_seconds = Integer(string="Time on task (sec)", default=0)
    edit_count = Integer(string="Edits before submit", default=0)
    abandoned_once = Boolean(string="Almost left", default=False)

    # --- Derived signals (stored for list/sort) -----------------------------
    text_sentiment = Float(
        compute="_compute_signals", store=True, string="Sentiment score"
    )
    sentiment_readout = Char(
        compute="_compute_signals", store=True, string="Sentiment"
    )
    tone_label = Char(compute="_compute_signals", store=True, string="Tone")
    emotion_tags = Char(compute="_compute_signals", store=True, string="Emotions")
    topic_hints = Char(compute="_compute_signals", store=True, string="Topics")
    mood_noise_score = Float(
        compute="_compute_signals", store=True, string="Mood noise score"
    )
    mood_noise_readout = Char(
        compute="_compute_signals", store=True, string="Mood noise"
    )
    signal_confidence_score = Float(
        compute="_compute_signals", store=True, string="Confidence score"
    )
    confidence_readout = Char(
        compute="_compute_signals", store=True, string="Confidence"
    )
    insight_summary = Char(compute="_compute_signals", store=True, string="Insight")
    analysis_source = Char(
        compute="_compute_signals", store=True, string="Analyzer"
    )
    active = Boolean(default=True)

    # --- Human verification (gold labels for few-shot / export) ---------------
    signals_verified = Boolean(string="Verified by human", default=False)
    verified_tone = Char(string="Verified tone")
    verified_emotions = Char(string="Verified emotions")
    verified_topics = Char(string="Verified topics")
    verified_insight = Text(string="Verified insight")
    verified_sentiment = Float(string="Verified sentiment")
    verified_notes = Text(string="Verification notes")

    @depends(
        "surface",
        "story_goal",
        "story_outcome",
        "story_blocker",
        "explicit_rating",
        "effort_seconds",
        "edit_count",
    )
    def _compute_signals(self):
        for record in self:
            result = analyze_record_once(record)
            signals = result.signals
            record.text_sentiment = signals.sentiment
            record.sentiment_readout = sentiment_readout(signals.sentiment)
            record.tone_label = signals.tone
            record.emotion_tags = ", ".join(signals.emotions)
            record.topic_hints = ", ".join(signals.topics)
            record.mood_noise_score = result.mood_noise_score
            record.mood_noise_readout = mood_noise_readout(result.mood_noise_score)
            record.signal_confidence_score = result.signal_confidence_score
            record.confidence_readout = confidence_readout(
                result.signal_confidence_score
            )
            record.analysis_source = signals.source
            record.insight_summary = result.insight_summary

    def create(self, vals: dict[str, Any]) -> "FeedbackIntake":
        rec = super().create(vals)
        schedule_llm_analysis(self.env, [rec.id])
        return rec

    def write(self, vals: dict[str, Any]) -> None:
        touch_llm = story_fields_changed(vals)
        super().write(vals)
        if touch_llm and self._ids:
            schedule_llm_analysis(self.env, list(self._ids))
