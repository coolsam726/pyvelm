"""Roll up feedback.intake rows into dashboard metrics."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class AnalyticsSnapshot:
    total: int = 0
    llm_count: int = 0
    lexicon_count: int = 0
    avg_sentiment: float | None = None
    avg_mood_noise: float | None = None
    avg_confidence: float | None = None
    high_mood_noise: int = 0
    negative_tone: int = 0
    positive_tone: int = 0
    tones: list[tuple[str, int]] = field(default_factory=list)
    surfaces: list[tuple[str, int, float | None]] = field(default_factory=list)
    emotions: list[tuple[str, int]] = field(default_factory=list)
    topics: list[tuple[str, int]] = field(default_factory=list)
    alerts: list[dict[str, str]] = field(default_factory=list)


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def gather_analytics(records) -> AnalyticsSnapshot:
    """Build dashboard numbers from a ``feedback.intake`` recordset."""
    snap = AnalyticsSnapshot()
    ids = list(records._ids) if records else []
    snap.total = len(ids)
    if not ids:
        return snap

    tone_counter: Counter[str] = Counter()
    surface_counter: Counter[str] = Counter()
    surface_noise: dict[str, list[float]] = {}
    emotion_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    sentiments: list[float] = []
    noises: list[float] = []
    confidences: list[float] = []

    for rec in records:
        if rec.analysis_source == "llm":
            snap.llm_count += 1
        else:
            snap.lexicon_count += 1

        tone = rec.tone_label or "unknown"
        tone_counter[tone] += 1
        if tone == "negative":
            snap.negative_tone += 1
        elif tone == "positive":
            snap.positive_tone += 1

        surf = rec.surface or "unknown"
        surface_counter[surf] += 1
        if rec.mood_noise_score is not None:
            surface_noise.setdefault(surf, []).append(float(rec.mood_noise_score))
            noises.append(float(rec.mood_noise_score))
            if float(rec.mood_noise_score) >= 0.55:
                snap.high_mood_noise += 1
                snap.alerts.append(
                    {
                        "surface": surf,
                        "insight": rec.insight_summary or "",
                        "mood_noise": f"{rec.mood_noise_score:.2f}",
                        "id": str(rec.id),
                    }
                )

        if rec.text_sentiment is not None:
            sentiments.append(float(rec.text_sentiment))
        if rec.signal_confidence_score is not None:
            confidences.append(float(rec.signal_confidence_score))

        for em in _split_tags(rec.emotion_tags):
            emotion_counter[em] += 1
        for tp in _split_tags(rec.topic_hints):
            topic_counter[tp] += 1

    if sentiments:
        snap.avg_sentiment = round(sum(sentiments) / len(sentiments), 3)
    if noises:
        snap.avg_mood_noise = round(sum(noises) / len(noises), 3)
    if confidences:
        snap.avg_confidence = round(sum(confidences) / len(confidences), 3)

    snap.tones = tone_counter.most_common()
    snap.emotions = emotion_counter.most_common(6)
    snap.topics = topic_counter.most_common(6)
    snap.surfaces = [
        (
            name,
            count,
            round(sum(surface_noise.get(name, [])) / len(surface_noise[name]), 3)
            if surface_noise.get(name)
            else None,
        )
        for name, count in surface_counter.most_common()
    ]
    snap.alerts.sort(key=lambda a: float(a["mood_noise"]), reverse=True)
    snap.alerts = snap.alerts[:8]
    return snap
