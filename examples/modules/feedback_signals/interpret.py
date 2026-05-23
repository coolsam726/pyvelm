"""Human-readable labels for feedback signal scores."""
from __future__ import annotations


def sentiment_readout(score: float | None) -> str:
    """``text_sentiment`` is −1 (unhappy story) to +1 (happy story)."""
    if score is None:
        return "—"
    s = float(score)
    if s >= 0.55:
        band = "Strongly positive"
    elif s >= 0.35:
        band = "Positive"
    elif s <= -0.55:
        band = "Strongly negative"
    elif s <= -0.35:
        band = "Negative"
    elif s > 0.08:
        band = "Slightly positive"
    elif s < -0.08:
        band = "Slightly negative"
    else:
        band = "Neutral"
    return f"{band} ({s:+.2f})"


def mood_noise_readout(score: float | None) -> str:
    """``mood_noise_score`` is 0–1: stars vs story disagreement."""
    if score is None:
        return "—"
    s = float(score)
    if s >= 0.55:
        return f"High ({s:.2f}) — stars likely mood, not product"
    if s >= 0.35:
        return f"Medium ({s:.2f}) — rating and story partly disagree"
    if s >= 0.15:
        return f"Low ({s:.2f}) — mostly aligned"
    return f"Minimal ({s:.2f}) — story and stars agree"


def confidence_readout(score: float | None) -> str:
    """``signal_confidence_score`` is 0–1: enough text to trust the insight."""
    if score is None:
        return "—"
    s = float(score)
    if s >= 0.75:
        return f"Strong ({s:.0%}) — rich narrative"
    if s >= 0.5:
        return f"Moderate ({s:.0%}) — usable signal"
    if s >= 0.3:
        return f"Thin ({s:.0%}) — short or sparse"
    return f"Weak ({s:.0%}) — mostly rating, little story"


SIGNAL_GLOSSARY: list[dict[str, str]] = [
    {
        "name": "Text sentiment",
        "range": "−1 to +1",
        "meaning": (
            "How positive or negative the written story reads. "
            "−1 is strongly unhappy; +1 is strongly happy. "
            "This comes from the narrative, not the star rating."
        ),
    },
    {
        "name": "Mood noise",
        "range": "0 to 1",
        "meaning": (
            "How much optional stars disagree with the story. "
            "High values (≥0.55) suggest the user rated their mood, "
            "not the product — down-weight the stars in decisions."
        ),
    },
    {
        "name": "Confidence",
        "range": "0 to 1",
        "meaning": (
            "How much signal we had beyond a bare rating — word count "
            "and fields filled. Low confidence means treat the insight cautiously."
        ),
    },
    {
        "name": "Tone",
        "range": "positive / negative / mixed / neutral",
        "meaning": "Broad bucket derived from sentiment and emotion words.",
    },
    {
        "name": "Emotions & topics",
        "range": "tags",
        "meaning": (
            "Primary feelings (frustration, delight, …) and product areas "
            "(billing, onboarding, …) detected in the story."
        ),
    },
]
