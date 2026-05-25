"""Materialise scaffold templates onto disk.

The scaffolder ships template files inside the wheel under
``pyvelm/scaffolds/<kind>/``. Each file is one of three shapes:

  * **Plain file** — copied as-is.
  * **`*.template`** — content is read as UTF-8, ``{{var}}``
    placeholders are substituted, the ``.template`` suffix is
    stripped from the destination name.
  * **`dotfoo`-prefixed name** — renamed to ``.foo`` on copy so
    setuptools doesn't have to ship dotfiles inside the wheel
    (some packaging configurations strip them).

The same machinery powers ``pyvelm init`` (a whole project) and
``pyvelm new`` (a single module). Each entry point points the
scaffolder at a different sub-tree.
"""
from __future__ import annotations

import re
import sys
from importlib import resources
from importlib.abc import Traversable
from pathlib import Path

# Valid project / module name: starts with a letter, then letters /
# digits / underscores. Length 1-50 — a reasonable upper bound that
# fits in a filesystem name without crowding ``ir_module.name``.
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")


def valid_name(name: str) -> bool:
    """True iff `name` is safe to use as a project / module name."""
    return bool(_NAME_RE.match(name))


def materialise(
    scaffold_kind: str,
    target: Path,
    *,
    variables: dict[str, str],
) -> None:
    """Copy the scaffold tree for ``scaffold_kind`` into ``target``.

    ``scaffold_kind`` names the sub-directory under
    ``pyvelm/scaffolds/`` (e.g. ``"project"`` or ``"module"``).
    ``variables`` are the ``{{key}}`` substitutions applied to every
    ``*.template`` file. Raises ``FileExistsError`` if the target
    already exists — the caller decides whether to refuse or merge.
    """
    if target.exists():
        raise FileExistsError(f"{target} already exists")

    src_root = resources.files("pyvelm.scaffolds").joinpath(scaffold_kind)
    if not src_root.is_dir():
        raise RuntimeError(f"No bundled scaffold named {scaffold_kind!r}")

    target.mkdir(parents=True)
    _copy_tree(src_root, target, variables)


def _copy_tree(
    src: Traversable,
    dst: Path,
    variables: dict[str, str],
) -> None:
    for entry in src.iterdir():
        # Substitute placeholders in filenames so a template named
        # `{{name}}.py.template` materialises as `tasks.py` for
        # `name=tasks`. Dotfile rename runs after substitution so
        # `dot{{name}}rc` would become `.tasksrc` (no use case yet,
        # but the order keeps the rules composable).
        out_name = _substitute(entry.name, variables)
        out_name = _rename_dotfile(out_name)
        if entry.is_dir():
            out_dir = dst / out_name
            out_dir.mkdir(exist_ok=True)
            _copy_tree(entry, out_dir, variables)
        else:
            _copy_file(entry, dst, out_name, variables)


def _rename_dotfile(name: str) -> str:
    """Bundled name `dotgitignore` becomes filesystem name `.gitignore`.

    Dotfiles inside the wheel are unreliable across packaging
    configurations — we ship them with a ``dot`` prefix and rename
    here. Only triggers on `dot<alpha>` so a real `dotfile` package
    (no such thing today, just future-proofing) wouldn't accidentally
    get rewritten.
    """
    if name.startswith("dot") and len(name) > 3 and name[3].isalpha():
        return "." + name[3:]
    return name


def _copy_file(
    src: Traversable,
    dst_dir: Path,
    out_name: str,
    variables: dict[str, str],
) -> None:
    is_template = out_name.endswith(".template")
    if is_template:
        out_name = out_name[: -len(".template")]
    dst = dst_dir / out_name

    with src.open("rb") as f:
        raw = f.read()

    if is_template:
        text = raw.decode("utf-8")
        text = _substitute(text, variables)
        dst.write_text(text, encoding="utf-8")
    else:
        dst.write_bytes(raw)


def echo_next_steps_for_new(module_name: str, modules_root: Path) -> None:
    """Print the post-`pyvelm new` walkthrough."""
    msg = f"""
Created {modules_root / module_name}/

Next steps:
  1. Restart your dev server (or `docker compose restart app`).
  2. Visit /web/apps in the browser.
  3. Find "{module_name}" in the catalog and click Install.

Add models, views, and menus with generators:
  pyvelm make:model {module_name}.product --module={module_name}
  pyvelm make:view {module_name}.product --module={module_name}
  pyvelm make:menu --view=product.list --module={module_name}
  pyvelm db autogen {module_name} --with-views

Optional: pyvelm make:command {module_name}:hello --module={module_name}
""".rstrip()
    print(msg, file=sys.stderr)


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _substitute(text: str, variables: dict[str, str]) -> str:
    """Replace ``{{ key }}`` placeholders. Unknown keys raise rather
    than silently leaving stray markers in the output."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            raise KeyError(
                f"Scaffold placeholder {{{{{key}}}}} has no value"
            )
        return variables[key]

    return _PLACEHOLDER_RE.sub(repl, text)


def find_modules_root(start: Path | None = None) -> Path | None:
    """Walk upward from ``start`` looking for ``pyvelm.toml`` and
    return the configured ``modules_root`` path (resolved against the
    project root). Returns ``None`` if no ``pyvelm.toml`` is found.

    The `pyvelm new` subcommand uses this so users don't have to
    pass ``--in`` from inside an init'd project.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        marker = candidate / "pyvelm.toml"
        if marker.is_file():
            return _read_modules_root(marker)
    return None


def _read_modules_root(marker: Path) -> Path:
    """Parse a minimal pyvelm.toml. We avoid tomllib in case a future
    user has the marker file but a 3.10 venv (tomllib landed in 3.11);
    a simple line-grep covers our single key.
    """
    text = marker.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("modules_root"):
            _, _, rhs = line.partition("=")
            rhs = rhs.strip().strip('"').strip("'")
            if rhs:
                return (marker.parent / rhs).resolve()
    # Sensible default if the marker exists but omits the key.
    return (marker.parent / "app" / "modules").resolve()


def echo_next_steps_for_init(project_name: str) -> None:
    """Print a friendly walkthrough after `pyvelm init` succeeds."""
    msg = f"""
Created ./{project_name}/

Next steps:
  cd {project_name}
  cp .env.example .env             # set PYVELM_DSN
  docker compose up --build        # → http://localhost:8000/login

Or without docker:
  python3 -m venv venv
  source venv/bin/activate
  pip install -e .
  python -m app.serve

Add a module:
  pyvelm new my_module
  pyvelm db autogen my_module    # after you add models
  pyvelm db migrate              # install/upgrade (also runs in compose)
""".rstrip()
    print(msg, file=sys.stderr)
