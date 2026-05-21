# API reference

Generated from docstrings via
[`mkdocstrings`](https://mkdocstrings.github.io/).

The reference covers the framework package only — bundled modules
(`base`, `admin`) and example addons (`partners`, `crm`, etc.)
declare data, not API.

## Layout

- **Recordsets & fields** — the ORM core. Start with
  [`pyvelm.model`](model.md) (BaseModel + recordsets), then
  [`pyvelm.fields`](fields.md) (Char / Integer / Many2one / …).
- **Modules & loader** — how `__pyvelm__.py` manifests get picked up,
  installed, and upgraded.
- **Views & rendering** — view inheritance + the HTMX/Jinja renderer.
- **Workflows** — server actions, automation rules, cron, mail.
- **HTTP & CLI** — the FastAPI app factory and the `pyvelm-cron`
  background runner.

## Conventions

- Private names (`_leading_underscore`) are filtered out by default;
  they show up only when documented explicitly.
- `Args:` / `Returns:` / `Raises:` blocks render as tables;
  free-form paragraphs render as Markdown.
- "Source" links at each entry jump straight to the line on GitHub.
