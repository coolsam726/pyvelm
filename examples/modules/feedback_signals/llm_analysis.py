"""LLM analysis for feedback_signals — Ollama (local) or OpenRouter (hosted).

Set ``LLM_PROVIDER`` to ``ollama`` or ``openrouter``. When unset: uses OpenRouter
if ``OPENROUTER_API_KEY`` is set, otherwise tries local Ollama.

Background jobs call this module; sync submit uses lexicon only (see signals_cache).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal

import httpx

from feedback_signals.analysis import TextSignals, analyze_lexicon
from feedback_signals.llm_circuit import (
    backoff_seconds_for_error,
    reset as circuit_reset,
    should_skip_llm,
    trip as circuit_trip,
)

_log = logging.getLogger(__name__)

Provider = Literal["ollama", "openrouter"]

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"
_OLLAMA_DEFAULT_BASE = "http://127.0.0.1:11434"
_OLLAMA_DEFAULT_MODEL = "qwen2.5:3b"
_OPENROUTER_TIMEOUT = 25.0
_OLLAMA_TIMEOUT = 120.0

_SUGGESTED_OLLAMA_MODELS = ("qwen2.5:3b", "llama3.2:3b", "gemma2:2b", "mistral:7b")

_ALLOWED_TONES = frozenset({"positive", "negative", "neutral", "mixed"})
_ALLOWED_EMOTIONS = frozenset(
    {"frustration", "confusion", "delight", "urgency", "distrust"}
)
_ALLOWED_TOPICS = frozenset(
    {
        "performance",
        "onboarding",
        "billing",
        "support",
        "accessibility",
        "data_loss",
    }
)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

_SYSTEM_PROMPT = (
    "You classify product feedback for a support team. "
    "Be faithful to the user's words; do not invent facts. "
    "If the story is negative, never label primary emotion as delight. "
    "Output valid JSON only, no markdown."
)


class ChatCompletionError(Exception):
    """API returned an error payload instead of a completion."""


def resolve_provider() -> Provider | None:
    """Which LLM backend to use, or None for lexicon-only."""
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if explicit in ("none", "off", "lexicon", ""):
        if explicit in ("none", "off", "lexicon"):
            return None
    if explicit == "ollama":
        return "ollama"
    if explicit == "openrouter":
        return "openrouter" if os.environ.get("OPENROUTER_API_KEY", "").strip() else None
    # Auto: OpenRouter when keyed, else local Ollama
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return "openrouter"
    if os.environ.get("OLLAMA_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return None
    return "ollama"


def ollama_chat_url() -> str:
    base = os.environ.get("OLLAMA_BASE_URL", _OLLAMA_DEFAULT_BASE).strip()
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    if base.endswith("/api"):
        return f"{base}/v1/chat/completions"
    return f"{base}/v1/chat/completions"


def _word_count(*parts: str | None) -> int:
    combined = " ".join(p for p in parts if p)
    return len(re.findall(r"\S+", combined))


def _extract_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    block = _JSON_BLOCK.search(text)
    if block:
        text = block.group(1).strip()
    return json.loads(text)


def _api_error_message(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or err)
    if err:
        return str(err)
    return None


def _parse_completion_body(body: dict[str, Any], *, provider: Provider) -> dict[str, Any]:
    api_err = _api_error_message(body)
    if api_err:
        raise ChatCompletionError(api_err)

    choices = body.get("choices")
    if not choices:
        raise ChatCompletionError(
            f"{provider} returned no choices (model={body.get('model', '?')!r})"
        )

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise ChatCompletionError(f"{provider} returned an empty message")

    return _extract_json(content)


def _build_messages(
    *,
    surface: str | None,
    story_goal: str | None,
    story_outcome: str | None,
    story_blocker: str | None,
    explicit_rating: int | None,
    few_shot_block: str = "",
) -> list[dict[str, str]]:
    lines = [
        "Analyze this product feedback. The user's written story is the primary signal;",
        "star ratings may reflect mood and can disagree with the narrative.",
        "",
        f"Surface (where in product): {surface or 'unknown'}",
        f"What they were trying to do: {story_goal or '(empty)'}",
        f"What happened: {story_outcome or '(empty)'}",
        f"What got in the way: {story_blocker or '(empty)'}",
    ]
    if explicit_rating:
        lines.append(f"Optional star rating (1-5): {explicit_rating}")
    else:
        lines.append("Optional star rating: not provided")
    lines.append("")
    lines.append(
        "Return JSON only with keys: sentiment (number -1 to 1), tone "
        "(positive|negative|neutral|mixed), emotions (array, up to 3 from: "
        "frustration, confusion, delight, urgency, distrust), topics (array, "
        "up to 3 from: performance, onboarding, billing, support, accessibility, "
        "data_loss), insight_summary (one concise sentence, max 120 chars, for "
        "operators — mention mood/rating mismatch if stars contradict the story)."
    )
    if few_shot_block:
        lines.append(few_shot_block)
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _chat_completion(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    provider: Provider,
) -> dict[str, Any]:
    resp = client.post(url, headers=headers, json=payload)
    if resp.status_code >= 400:
        detail = resp.text[:300]
        try:
            parsed = resp.json()
            api_err = _api_error_message(parsed)
            if api_err:
                detail = api_err
        except (json.JSONDecodeError, TypeError):
            pass
        raise httpx.HTTPStatusError(
            f"{resp.status_code} {detail}",
            request=resp.request,
            response=resp,
        )

    body = resp.json()
    api_err = _api_error_message(body)
    if api_err and not body.get("choices"):
        raise ChatCompletionError(api_err)
    return body


def _call_ollama(
    client: httpx.Client,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    model = os.environ.get("OLLAMA_MODEL", _OLLAMA_DEFAULT_MODEL).strip()
    model = model or _OLLAMA_DEFAULT_MODEL
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    # Ollama supports format=json on newer versions
    if os.environ.get("OLLAMA_JSON_FORMAT", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        payload["format"] = "json"

    headers = {"Content-Type": "application/json"}
    return _chat_completion(
        client,
        url=ollama_chat_url(),
        headers=headers,
        payload=payload,
        provider="ollama",
    )


def _call_openrouter(
    client: httpx.Client,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = (
        os.environ.get("OPENROUTER_MODEL", _OPENROUTER_DEFAULT_MODEL).strip()
        or _OPENROUTER_DEFAULT_MODEL
    )
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "messages": messages,
    }
    if os.environ.get("OPENROUTER_JSON_MODE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "http://localhost:8000"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "pyvelm feedback_signals demo"),
    }
    return _chat_completion(
        client,
        url=_OPENROUTER_URL,
        headers=headers,
        payload=payload,
        provider="openrouter",
    )


def _clamp_sentiment(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, round(score, 3)))


def _filter_labels(values: Any, allowed: frozenset[str], *, limit: int = 3) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for raw in values:
        label = str(raw).strip().lower().replace(" ", "_")
        if label in allowed and label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out


def _normalize_tone(value: Any, sentiment: float) -> str:
    tone = str(value or "").strip().lower()
    if tone in _ALLOWED_TONES:
        return tone
    if sentiment >= 0.35:
        return "positive"
    if sentiment <= -0.35:
        return "negative"
    return "neutral"


def _signals_from_json(
    data: dict[str, Any],
    *,
    provider: Provider,
    story_goal: str | None,
    story_outcome: str | None,
    story_blocker: str | None,
    explicit_rating: int | None,
    wc: int,
) -> TextSignals:
    sentiment = _clamp_sentiment(data.get("sentiment"))
    tone = _normalize_tone(data.get("tone"), sentiment)
    emotions = _filter_labels(data.get("emotions"), _ALLOWED_EMOTIONS)
    topics = _filter_labels(data.get("topics"), _ALLOWED_TOPICS)
    insight = str(data.get("insight_summary") or "").strip()[:240]

    if not emotions:
        if sentiment < -0.2:
            emotions = ["frustration"]
        elif sentiment > 0.2:
            emotions = ["delight"]

    if not insight:
        from feedback_signals.analysis import build_insight, mood_noise

        fallback = analyze_lexicon(story_goal, story_outcome, story_blocker)
        insight = build_insight(
            tone=tone,
            emotions=emotions or fallback.emotions,
            topics=topics or fallback.topics,
            mood_noise_score=mood_noise(explicit_rating, sentiment, wc),
            sentiment=sentiment,
            word_count=wc,
        )

    return TextSignals(
        word_count=wc,
        sentiment=sentiment,
        tone=tone,
        emotions=emotions,
        topics=topics,
        insight_summary=insight,
        source=provider,
    )


def try_llm_analysis(
    *,
    surface: str | None = None,
    story_goal: str | None = None,
    story_outcome: str | None = None,
    story_blocker: str | None = None,
    explicit_rating: int | None = None,
    few_shot_block: str = "",
) -> TextSignals | None:
    """Call configured LLM provider; return ``TextSignals`` or ``None`` (lexicon)."""
    provider = resolve_provider()
    if provider is None:
        return None

    if should_skip_llm():
        return None

    wc = _word_count(story_goal, story_outcome, story_blocker)
    if wc < 3:
        return None

    messages = _build_messages(
        surface=surface,
        story_goal=story_goal,
        story_outcome=story_outcome,
        story_blocker=story_blocker,
        explicit_rating=explicit_rating,
        few_shot_block=few_shot_block,
    )
    timeout = _OLLAMA_TIMEOUT if provider == "ollama" else _OPENROUTER_TIMEOUT

    try:
        with httpx.Client(timeout=timeout) as client:
            if provider == "ollama":
                body = _call_ollama(client, messages)
            else:
                body = _call_openrouter(client, messages)
        data = _parse_completion_body(body, provider=provider)
        circuit_reset()
    except Exception as exc:  # noqa: BLE001
        hint = ""
        err = str(exc).lower()
        if provider == "ollama" and (
            "connection refused" in err or "connect" in err
        ):
            hint = (
                f" Is Ollama running? Try: ollama pull {_OLLAMA_DEFAULT_MODEL} "
                f"and ollama serve — models: {', '.join(_SUGGESTED_OLLAMA_MODELS)}"
            )
        elif "429" in err or "rate" in err:
            hint = " Rate-limited — use LLM_PROVIDER=ollama for local testing."
        circuit_trip(str(exc), seconds=backoff_seconds_for_error(exc))
        _log.warning(
            "%s analysis failed, using lexicon: %s.%s",
            provider,
            exc,
            hint,
        )
        return None

    return _signals_from_json(
        data,
        provider=provider,
        story_goal=story_goal,
        story_outcome=story_outcome,
        story_blocker=story_blocker,
        explicit_rating=explicit_rating,
        wc=wc,
    )


# Backward-compatible alias
try_openrouter_analysis = try_llm_analysis
