# Console commands (Artisan-style)

pyvelm supports **custom CLI commands** like Laravel Artisan. Modules
ship generators, maintenance tasks, and importers as Python classes;
users run them as:

```bash
pyvelm make:module inventory
pyvelm inventory:import --file=data.csv
pyvelm list
pyvelm help make:module
```

Built-in framework commands (`cron`, `init`, `new`, `db`) stay as they
are. Everything else is discovered from installed modules.

## Writing a command

Subclass :class:`pyvelm.console.Command` and place the file in your
module's `commands/` directory (or register it in `COMMANDS`).

```python
# app/modules/inventory/commands/import_products.py
from pyvelm.console import Command


class ImportProductsCommand(Command):
    name = "inventory:import"
    description = "Import products from a CSV file"
    signature = "inventory:import {path} {--dry-run}"
    requires_db = True  # loads PYVELM_DSN + registry before handle()

    def handle(self, path: str, dry_run: bool = False) -> int:
        self.info(f"Importing {path}…")
        if dry_run:
            self.warn("Dry run — no writes.")
        # self.env is available when requires_db=True
        return 0
```

### Signature tokens

| Token | Meaning |
|-------|---------|
| `{name}` | Required positional argument |
| `{name?}` | Optional positional |
| `{--flag}` | Boolean flag (`store_true`) |
| `{--opt=}` | Optional option (value after `=`) |
| `{--opt=default}` | Option with default |
| `{name : Help text}` | Description shown in `--help` |

Use a **namespace** in the command name (`inventory:import`, `make:module`)
so app commands don't collide.

## Registration

**Auto-discovery (recommended):** any `Command` subclass under
`<module>/commands/*.py` is registered when the module is discovered.

**Explicit manifest:** list dotted paths in `__pyvelm__.py`:

```python
COMMANDS = [
    "inventory.commands.import_products:ImportProductsCommand",
]
```

Discovery uses the same module roots as the web app (`pyvelm.toml`
`modules_root`, `PYVELM_MODULE_ROOTS`, bundled `base` / `admin` /
`console`).

## Generators (bundled `console` module)

| Command | Purpose |
|---------|---------|
| `make:module` | Empty addon skeleton (no models/views/menus) |
| `make:model` | `models/<name>.py` + `models/__init__.py` import (`--vellum` for Vellum mixin) |
| `make:view` | `views/<stem>.py` list + form + `DATA` entry (from model fields by default) |
| `make:menu` | `views/menu.py` (or `--append` to existing) |
| `make:command` | `commands/<name>.py` Artisan command class |

Typical workflow:

```bash
cd my_erp
pyvelm make:module inventory
pyvelm make:model inventory.product --module=inventory
pyvelm make:model blog.post --module=blog --vellum   # Vellum + _guarded scaffold
pyvelm make:view inventory.product --module=inventory
# Default: introspect stored fields → list columns + form sections
# (booleans → toggle, O2m/M2m → widget="dialog"). Use --minimal for name-only stub.
pyvelm make:menu --view=product.list --module=inventory
pyvelm db autogen inventory --with-views   # migration + views for new models
docker compose restart app
# Install via /web/apps
```

`pyvelm db autogen <module> --with-views` creates list+form views for any
model touched by the schema diff that does not already have a list view.

## API reference

- :class:`pyvelm.console.Command` — base class
- :class:`pyvelm.console.CommandContext` — `info`, `line`, `warn`, `error`
- :func:`pyvelm.loader.discover_commands` — build a registry programmatically

See also [CLI reference](cli.md).
