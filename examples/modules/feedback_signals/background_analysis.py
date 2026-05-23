"""Background OpenRouter analysis — never block submit/save."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyvelm import Environment, Registry

_log = logging.getLogger(__name__)

_pool = None
_registry = None
_executor: ThreadPoolExecutor | None = None

_STORY_FIELDS = frozenset(
    {
        "surface",
        "story_goal",
        "story_outcome",
        "story_blocker",
        "explicit_rating",
    }
)


def configure(pool, registry) -> None:
    """Called once from ``register_routes`` (examples/serve.py)."""
    global _pool, _registry, _executor
    _pool = pool
    _registry = registry
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="feedback-llm",
        )


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def schedule_llm_analysis(env, record_ids: list[int]) -> None:
    """Queue LLM re-analysis; returns immediately."""
    if not record_ids or _pool is None or _registry is None or _executor is None:
        return
    uid = env.uid
    ids = [int(i) for i in record_ids if i]
    if not ids:
        return
    _executor.submit(_run_llm_analysis, ids, uid)


def story_fields_changed(vals: dict) -> bool:
    return bool(_STORY_FIELDS & set(vals.keys()))


def _run_llm_analysis(record_ids: list[int], uid: int | None) -> None:
    """Worker: try OpenRouter; on failure keep existing lexicon signals."""
    from pyvelm import Environment

    from feedback_signals.llm_circuit import should_skip_llm
    from feedback_signals.signals_cache import clear_analysis_cache

    if should_skip_llm():
        return

    try:
        with _pool.connection() as conn:
            env = Environment(conn, registry=_registry, uid=uid)
            env = env.with_context(feedback_signals_llm=True)
            Intake = env["feedback.intake"]
            for rid in record_ids:
                try:
                    recs = Intake.search([("id", "=", rid)], limit=1)
                    if not recs:
                        continue
                    recs.ensure_one()
                    clear_analysis_cache(env)
                    with env.transaction():
                        # Touch narrative fields → recompute with LLM context.
                        recs.write(
                            {
                                "story_goal": recs.story_goal,
                                "story_outcome": recs.story_outcome,
                                "story_blocker": recs.story_blocker,
                            }
                        )
                except Exception:  # noqa: BLE001 — per-record isolation
                    _log.debug(
                        "Background LLM analysis failed for intake %s",
                        rid,
                        exc_info=True,
                    )
    except Exception:
        _log.debug("Background LLM worker failed", exc_info=True)
