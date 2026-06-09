# Unreleased (main branch)

Features on `main` not yet tagged on PyPI. See also
[CHANGELOG](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md#unreleased).

---

## Highlights

### Fluent module manifests

Assign a velmphp-style builder to ``manifest`` in ``__pyvelm__.py``:

```python
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("partners")
    .version(0, 4, 0)
    .depends("base")
    .data("views/partner.py", "views/menu.py")
    .install_hook("partners.hooks:install")
    .summary("Companies, contacts, and the partner directory.")
)
```

Legacy ``NAME`` / ``VERSION`` / ``DEPENDS`` / ``DATA`` constants remain supported.
``pyvelm make:module`` and migration tooling patch ``.version(...)`` and
``.data(...)`` on fluent manifests.

See [Modules → The manifest](../modules.md#the-manifest).

### Fluent view and menu builders

Declare views and menus with class-based builders (Filament / velmphp style):

```python
from pyvelm.builders import Field, FormView, ListView, Menus, ViewsData

m = Menus("partners")
views_data = (
    ViewsData.make()
    .views(
        ListView.make("partner.list")
        .model("res.partner")
        .columns(["name", Field.make("active").toggle()])
        .form_view("partner.form"),
        FormView.make("partner.form")
        .model("res.partner")
        .section("identity", "Identity", ["name", "code"]),
    )
    .menus(
        m.group("business", "Business", icon="home").children([
            m.item("business.partners", "Partners").view("partner.list"),
        ]),
    )
)
```

Legacy ``list_view`` / ``field`` / ``section`` functions still work and produce
the same dicts. ``make:view`` scaffolds emit the fluent style.

See [Building UIs](../views.md) and [Modules → Data files](../modules.md#data-files).

### `models.Model` base class

Odoo-style authoring for new models and ``_inherit`` extensions:

```python
from pyvelm import Char, models

class Partner(models.Model):
    _inherit = "res.partner"
    vip_note = Char()
```

``models.Model`` is an alias of :class:`~pyvelm.BaseModel`; use whichever reads
naturally in your module.

See [Declaring models → Extending an existing model](../models.md#extending-an-existing-model).

### ORM super chaining (v1.0.1+)

Stacked ``_inherit`` extensions can call ``super().write(vals)`` or
``self.super().write(vals)`` to reach the next layer. The registry records
``inherit_chain`` for introspection.

See [Declaring models → Super chaining](../models.md#super-chaining-create-write-custom-methods)
and the ``super_chain_demo*`` example modules under ``examples/modules/``.

### Vellum removed

The optional Vellum ORM mixin, ``env.query()``, bundled ``vellum`` module,
``vellum_demo`` example, and ``--vellum`` scaffold flag are gone.

**Mass assignment** (``_fillable`` / ``_guarded``) remains in
``pyvelm.mass_assignment`` for HTTP form writes.

---

## Upgrade from PyPI

When these land in a release:

```bash
pip install -U pyvelm
pyvelm db migrate
pyvelm make:stubs    # refresh IDE literals after view/model renames
```

Review custom modules that used Vellum or legacy-only manifest constants;
migrate to ``Manifest.make()`` and ``ViewsData.make()`` when convenient (not
required — legacy forms still load).
