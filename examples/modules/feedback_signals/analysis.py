"""Lightweight text analysis for the feedback_signals demo.

No ML dependencies — lexicon matching with basic negation handling so
frustrated stories are not misread as delight.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z']+")


@dataclass
class TextSignals:
    word_count: int = 0
    sentiment: float = 0.0
    tone: str = "neutral"
    emotions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    insight_summary: str | None = None
    source: str = "lexicon"  # "llm" when OpenRouter succeeded


# Keep only unambiguous positives — avoid tokens that appear in complaints
# ("nothing works", "not clear", "wasn't helpful").
_POSITIVE = frozenset(
    "love excellent amazing wonderful fantastic delighted happy pleased "
    "brilliant awesome perfect superb outstanding thrilled grateful".split()
)

_NEGATIVE = frozenset(
    "hate terrible awful broken confusing frustrating slow buggy useless "
    "annoying angry upset disappointed horrible worst bad worse fail failed "
    "error crash stuck blocked impossible unclear misleading waste painful "
    "furious ridiculous unacceptable nightmare pathetic garbage suck sucks "
    "disaster unacceptable unusable".split()
)

_NEGATORS = frozenset(
    "not no never neither nor dont doesn't isn't wasn't aren't won't wont "
    "can't cannot couldnt couldn't without hardly barely nothing nowhere "
    "neither".split()
)

# Intensifiers immediately before a negative adjective (e.g. "very frustrating").
_INTENSIFIERS = frozenset("very so too extremely incredibly really super quite".split())

_EMOTIONS: dict[str, frozenset[str]] = {
    "frustration": frozenset(
        "frustrated frustrating frustrates annoy annoyed annoying stuck blocked "
        "useless waste pointless angry furious hate terrible awful unacceptable "
        "nightmare ridiculous pathetic garbage sucks unusable fail failed "
        "disappointed disappointing broken slow".split()
    ),
    "confusion": frozenset(
        "confused confusing unclear lost understand unexpected surprising "
        "unclear misleading".split()
    ),
    "delight": frozenset(
        "love delighted amazing wonderful thrilled grateful outstanding "
        "delightful exceeded superb brilliant awesome perfect".split()
    ),
    "urgency": frozenset(
        "urgent asap immediately critical blocking production deadline "
        "emergency".split()
    ),
    "distrust": frozenset(
        "sketchy shady suspicious privacy scam misleading dishonest hidden "
        "fee sketchy".split()
    ),
}

# When sentiment is negative, prefer these emotions over delight in ordering.
_NEGATIVE_EMOTION_PRIORITY = (
    "frustration",
    "confusion",
    "urgency",
    "distrust",
    "delight",
)

_POSITIVE_EMOTION_PRIORITY = (
    "delight",
    "frustration",
    "confusion",
    "urgency",
    "distrust",
)

_TOPICS: dict[str, frozenset[str]] = {
    "performance": frozenset("slow lag loading spinner timeout freeze".split()),
    "onboarding": frozenset(
        "signup sign up register tutorial first time onboarding welcome intro".split()
    ),
    "billing": frozenset("price cost billing invoice charge payment refund".split()),
    "support": frozenset("support help ticket agent chat email response".split()),
    "accessibility": frozenset(
        "contrast screen reader keyboard tab focus blind vision color".split()
    ),
    "data_loss": frozenset("lost deleted gone missing unsaved overwrite".split()),
}


def _tokenize(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _negated_indices(tokens: list[str]) -> frozenset[int]:
    """Indices of tokens under the scope of a preceding negator (next 1–2 words)."""
    negated: set[int] = set()
    for i, token in enumerate(tokens):
        if token not in _NEGATORS:
            continue
        for j in range(i + 1, min(i + 3, len(tokens))):
            negated.add(j)
    return frozenset(negated)


def _is_negated(tokens: list[str], index: int) -> bool:
    return index in _negated_indices(tokens)


def _polarity_counts(tokens: list[str]) -> tuple[int, int]:
    pos = neg = 0
    for i, token in enumerate(tokens):
        negated = _is_negated(tokens, i)
        if token in _POSITIVE:
            if negated:
                neg += 1
            else:
                pos += 1
        elif token in _NEGATIVE:
            if negated:
                continue
            weight = 2 if i > 0 and tokens[i - 1] in _INTENSIFIERS else 1
            neg += weight
    return pos, neg


def _sentiment(tokens: list[str]) -> tuple[float, str]:
    if not tokens:
        return 0.0, "neutral"
    pos, neg = _polarity_counts(tokens)
    if pos == 0 and neg == 0:
        return 0.0, "neutral"
    raw = (pos - neg) / max(pos + neg, 1)
    score = max(-1.0, min(1.0, raw))
    if score >= 0.35:
        tone = "positive"
    elif score <= -0.35:
        tone = "negative"
    elif pos and neg:
        tone = "mixed"
    else:
        tone = "neutral"
    return score, tone


def _emotion_scores(tokens: list[str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for label, words in _EMOTIONS.items():
        total = 0
        for i, token in enumerate(tokens):
            if token in words and not _is_negated(tokens, i):
                weight = 2 if i > 0 and tokens[i - 1] in _INTENSIFIERS else 1
                total += weight
        if total:
            scores[label] = total
    return scores


def _rank_emotions(scores: dict[str, int], sentiment: float) -> list[str]:
    if not scores:
        return []
    # Never surface delight on clearly negative stories.
    if sentiment < -0.15 and scores.get("delight", 0) <= scores.get("frustration", 0):
        scores = {k: v for k, v in scores.items() if k != "delight"}
    if sentiment > 0.15:
        scores = {k: v for k, v in scores.items() if k != "frustration"}

    priority = (
        _NEGATIVE_EMOTION_PRIORITY
        if sentiment <= 0
        else _POSITIVE_EMOTION_PRIORITY
    )
    rank = {name: i for i, name in enumerate(priority)}

    ordered = sorted(
        scores.keys(),
        key=lambda name: (-scores[name], rank.get(name, 99)),
    )
    return ordered[:3]


def _match_buckets(
    tokens: list[str], buckets: dict[str, frozenset[str]]
) -> list[str]:
    hits: list[tuple[int, str]] = []
    for label, words in buckets.items():
        overlap = sum(
            1
            for i, t in enumerate(tokens)
            if t in words and not _is_negated(tokens, i)
        )
        if overlap:
            hits.append((overlap, label))
    hits.sort(reverse=True)
    return [label for _, label in hits[:3]]


def analyze_lexicon(*parts: str | None) -> TextSignals:
    """Derive signals from keyword/negation rules (offline fallback)."""
    combined = " ".join(p for p in parts if p)
    tokens = _tokenize(combined)
    sentiment, tone = _sentiment(tokens)
    emotions = _rank_emotions(_emotion_scores(tokens), sentiment)
    if not emotions:
        if sentiment < -0.35:
            emotions = ["frustration"]
        elif sentiment > 0.35:
            emotions = ["delight"]
    return TextSignals(
        word_count=len(tokens),
        sentiment=sentiment,
        tone=tone,
        emotions=emotions,
        topics=_match_buckets(tokens, _TOPICS),
        source="lexicon",
    )


def analyze_text(
    *parts: str | None,
    surface: str | None = None,
    explicit_rating: int | None = None,
    few_shot_block: str = "",
) -> TextSignals:
    """Analyze feedback: LLM when configured (Ollama/OpenRouter), else lexicon."""
    from feedback_signals.llm_analysis import try_llm_analysis

    llm = try_llm_analysis(
        surface=surface,
        story_goal=parts[0] if len(parts) > 0 else None,
        story_outcome=parts[1] if len(parts) > 1 else None,
        story_blocker=parts[2] if len(parts) > 2 else None,
        explicit_rating=explicit_rating,
        few_shot_block=few_shot_block,
    )
    if llm is not None:
        return llm
    return analyze_lexicon(*parts)


def mood_noise(explicit_rating: int | None, sentiment: float, word_count: int) -> float:
    """How much the star rating disagrees with narrative tone (0–1).

    High values suggest the rating reflects transient mood more than the story.
    Returns 0 when there is not enough text to compare.
    """
    if not explicit_rating or word_count < 4:
        return 0.0
    rating_axis = (explicit_rating - 3) / 2.0
    gap = abs(rating_axis - sentiment)
    strength = min(1.0, word_count / 12.0)
    return round(min(1.0, gap * strength * 1.15), 3)


def signal_confidence(
    word_count: int,
    fields_filled: int,
    total_fields: int = 4,
    *,
    source: str = "lexicon",
) -> float:
    """Rough 0–1 confidence that we have enough signal to trust insights."""
    text_part = min(1.0, word_count / 20.0)
    form_part = fields_filled / max(total_fields, 1)
    score = 0.55 * text_part + 0.45 * form_part
    if source == "llm":
        score = max(score, 0.72)
    return round(min(1.0, score), 3)


def build_insight(
    *,
    tone: str,
    emotions: list[str],
    topics: list[str],
    mood_noise_score: float,
    sentiment: float,
    word_count: int,
) -> str:
    if word_count < 3:
        return "Need more narrative — rating alone is weak signal"
    parts: list[str] = []
    if mood_noise_score >= 0.55:
        parts.append("Star rating likely mood-driven")
    elif mood_noise_score >= 0.35:
        parts.append("Rating and story partly disagree")
    if emotions:
        label = emotions[0]
        if label == "frustration":
            parts.append("Reads frustrated")
        elif label == "confusion":
            parts.append("Reads confused")
        elif label == "delight":
            parts.append("Reads delighted")
        elif label == "urgency":
            parts.append("Reads urgent")
        elif label == "distrust":
            parts.append("Reads wary")
        else:
            parts.append(f"Tone: {label}")
    if topics:
        parts.append(f"About: {', '.join(topics[:2])}")
    if not parts:
        if sentiment > 0.3:
            parts.append("Story reads genuinely positive")
        elif sentiment < -0.3:
            parts.append("Story reads genuinely negative")
        else:
            parts.append(f"Neutral narrative ({tone})")
    return " · ".join(parts)
