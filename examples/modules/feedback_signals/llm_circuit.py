"""Process-wide circuit breaker for LLM providers (Ollama, OpenRouter, …)."""
from __future__ import annotations

import logging
import os
import threading
import time

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_open_until: float = 0.0
_last_reason: str = ""
_failure_streak: int = 0
_skip_logged: bool = False


def _base_backoff_seconds() -> float:
    return float(
        os.environ.get("LLM_BACKOFF_SECONDS")
        or os.environ.get("OPENROUTER_BACKOFF_SECONDS", "90")
    )


def _max_backoff_seconds() -> float:
    return float(
        os.environ.get("LLM_BACKOFF_MAX")
        or os.environ.get("OPENROUTER_BACKOFF_MAX", "600")
    )


def backoff_remaining() -> float:
    with _lock:
        return max(0.0, _open_until - time.monotonic())


def is_circuit_open() -> bool:
    with _lock:
        if time.monotonic() >= _open_until:
            return False
        return True


def trip(reason: str, *, seconds: float | None = None) -> float:
    global _open_until, _last_reason, _failure_streak, _skip_logged
    with _lock:
        _failure_streak += 1
        if seconds is None:
            mult = min(8, 2 ** (_failure_streak - 1))
            seconds = min(_base_backoff_seconds() * mult, _max_backoff_seconds())
        duration = max(float(seconds), 5.0)
        _open_until = time.monotonic() + duration
        _last_reason = reason
        _skip_logged = False
    _log.warning(
        "LLM circuit open for %.0fs (%s). Using lexicon only until backoff ends.",
        duration,
        reason[:200],
    )
    return duration


def reset() -> None:
    global _open_until, _last_reason, _failure_streak, _skip_logged
    with _lock:
        if _failure_streak:
            _log.info("LLM circuit closed after successful call.")
        _open_until = 0.0
        _last_reason = ""
        _failure_streak = 0
        _skip_logged = False


def should_skip_llm() -> bool:
    if not is_circuit_open():
        return False
    global _skip_logged
    with _lock:
        if not _skip_logged:
            _skip_logged = True
            remaining = max(0.0, _open_until - time.monotonic())
            _log.info(
                "LLM skipped (circuit open %.0fs left: %s). Using lexicon.",
                remaining,
                _last_reason[:120] or "recent failure",
            )
    return True


def backoff_seconds_for_error(exc: BaseException) -> float | None:
    text = str(exc).lower()
    if "connection refused" in text or "failed to connect" in text:
        return float(os.environ.get("LLM_BACKOFF_CONNECT", "30"))
    if "429" in text or "rate" in text:
        return float(
            os.environ.get("OPENROUTER_BACKOFF_429")
            or os.environ.get("LLM_BACKOFF_429", "120")
        )
    if "404" in text or "no endpoints" in text:
        return float(
            os.environ.get("OPENROUTER_BACKOFF_404")
            or os.environ.get("LLM_BACKOFF_404", "300")
        )
    return None
