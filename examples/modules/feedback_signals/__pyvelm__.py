"""feedback_signals module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("feedback_signals")
    .version(0, 1, 0)
    .display_name("Feedback Signals")
    .summary(
        "Narrative-first feedback demo: Ollama or OpenRouter LLM (optional) "
        "with lexicon fallback."
    )
    .category("Demo")
    .author("pyvelm")
    .depends("base")
    .data(
        "views/intake.py",
        "views/dashboard.py",
        "views/menu.py",
    )
    .install_hook("feedback_signals.hooks:install")
    .sync_hook("feedback_signals.hooks:sync")
    .web_routes("feedback_signals.web:register_routes")
)
