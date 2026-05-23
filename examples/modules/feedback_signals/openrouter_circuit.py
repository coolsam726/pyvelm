"""Backward-compatible re-exports — use :mod:`feedback_signals.llm_circuit`."""
from feedback_signals.llm_circuit import (  # noqa: F401
    backoff_remaining,
    backoff_seconds_for_error,
    is_circuit_open,
    reset,
    should_skip_llm as should_skip_openrouter,
    trip,
)
