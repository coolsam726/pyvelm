# Unreleased (main branch)

Changes on `main` after the latest PyPI tag. See
[CHANGELOG](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md#unreleased).

---

## Highlights

- **Fluent ORM field builders** — ``Char().required().string("Name")``,
  ``Many2one("res.country").ondelete("SET NULL")``, etc. (constructor kwargs
  still supported). See [Declaring models → Fluent field chains](../models.md#fluent-field-chains-v12).
- **Nested create dialogs** — child ``PvDialog`` saves return to the parent form
  (e.g. create continent while creating a country).
- **Geo bootstrap** — install seeds continents + detected country only; full
  world import via **Seed geography data** (background + toast).
- **`WidgetHint`** — ``text``, ``html``, ``code``, ``file_url``, etc. on ``Char``
  fields without IDE/type errors.

---

## Upgrade from PyPI

When the next release ships:

```bash
pip install -U pyvelm
pyvelm db migrate
```
