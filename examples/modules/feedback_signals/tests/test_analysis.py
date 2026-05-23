"""Regression tests for feedback_signals.analysis."""

from feedback_signals.analysis import analyze_lexicon, build_insight, mood_noise


def test_frustration_not_delight():
    s = analyze_lexicon(
        "Pay for credits",
        "Payment failed, not impressed, very annoying",
        "",
    )
    assert "delight" not in s.emotions
    assert s.emotions[0] == "frustration"
    assert s.sentiment < 0


def test_nothing_works_is_negative():
    s = analyze_lexicon("Export", "Nothing works, I am furious", "")
    assert s.tone == "negative"
    assert s.emotions and s.emotions[0] == "frustration"


def test_genuine_delight_still_detected():
    s = analyze_lexicon(
        "Finish signup",
        "The tutorial was wonderful and I felt delighted",
        "",
    )
    assert "delight" in s.emotions
    assert s.sentiment > 0.3


def test_mood_noise_when_stars_disagree():
    s = analyze_lexicon(
        "Pay",
        "Billing confusing slow stuck frustrating",
        "",
    )
    assert mood_noise(5, s.sentiment, s.word_count) >= 0.35


def test_insight_says_frustrated_not_delighted():
    s = analyze_lexicon("Try", "So frustrating and stuck again", "")
    msg = build_insight(
        tone=s.tone,
        emotions=s.emotions,
        topics=s.topics,
        mood_noise_score=0.0,
        sentiment=s.sentiment,
        word_count=s.word_count,
    )
    assert "frustrat" in msg.lower()
    assert "delight" not in msg.lower()


def test_openrouter_json_extract():
    from feedback_signals.llm_analysis import _extract_json

    raw = '```json\n{"sentiment": -0.8, "tone": "negative"}\n```'
    data = _extract_json(raw)
    assert data["sentiment"] == -0.8


def test_openrouter_error_body():
    from feedback_signals.llm_analysis import ChatCompletionError, _parse_completion_body

    try:
        _parse_completion_body({"error": {"message": "Rate limit exceeded"}}, provider="openrouter")
    except ChatCompletionError as exc:
        assert "rate limit" in str(exc).lower()
    else:
        raise AssertionError("expected ChatCompletionError")
