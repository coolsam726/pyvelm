NAME: str = "feedback_signals"
DISPLAY_NAME: str = "Feedback Signals"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = (
    "Narrative-first feedback demo: Ollama or OpenRouter LLM (optional) "
    "with lexicon fallback."
)
CATEGORY: str = "Demo"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base"]
DATA: list[str] = [
    "views/intake.py",
    "views/dashboard.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "feedback_signals.hooks:install"
SYNC_HOOK: str = "feedback_signals.hooks:sync"
WEB_ROUTES: str = "feedback_signals.web:register_routes"
