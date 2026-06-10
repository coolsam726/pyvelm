#!/usr/bin/env python3
"""Bump pyvelm version across the repo for a release.

Usage::

    python scripts/bump_version.py 1.4.0
    python scripts/bump_version.py 1.4.0 --date 2026-06-15
    python scripts/bump_version.py --check

Moves ``## Unreleased`` in ``CHANGELOG.md`` to ``## [X.Y.Z] — <date>``,
updates ``pyproject.toml`` and ``pyvelm.__version__``, refreshes ``README.md``,
``docs/index.md``, and related docs pointers, and creates
``docs/releases/vX.Y.Z.md`` when missing.

After bumping, commit, then::

    ./scripts/tag_release.sh <version>
    git push && git push origin v<version>
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def repo_root(start: Path | None = None) -> Path:
    return (start or Path(__file__).resolve()).parents[1]


def parse_version(value: str) -> str:
    value = value.strip()
    if not _VERSION_RE.match(value):
        raise ValueError(f"Version must be X.Y.Z (got {value!r})")
    return value


def read_pyproject_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("version not found in pyproject.toml")
    return match.group(1)


def read_init_version(root: Path) -> str:
    text = (root / "pyvelm" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("__version__ not found in pyvelm/__init__.py")
    return match.group(1)


def check_versions(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        pyproject = read_pyproject_version(root)
    except ValueError as exc:
        return [str(exc)]
    try:
        init = read_init_version(root)
    except ValueError as exc:
        return [str(exc)]
    if pyproject != init:
        errors.append(
            f"pyproject.toml ({pyproject}) != pyvelm.__version__ ({init})"
        )
    return errors


def bump_pyproject(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'^version = "[^"]+"',
        f'version = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("could not update version in pyproject.toml")
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def bump_init(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'^__version__ = "[^"]+"',
        f'__version__ = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("could not update __version__ in pyvelm/__init__.py")
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def extract_unreleased_body(changelog_text: str) -> str:
    if "## Unreleased" not in changelog_text:
        raise ValueError("CHANGELOG.md has no ## Unreleased section")
    after = changelog_text.split("## Unreleased", 1)[1]
    match = re.search(r"\n## \[", after)
    body = after[: match.start()] if match else after
    return body.strip()


def _changelog_has_version(text: str, version: str) -> bool:
    return bool(re.search(rf"^## \[{re.escape(version)}\]", text, re.MULTILINE))


def finalize_changelog(path: Path, version: str, release_date: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if _changelog_has_version(text, version):
        return False
    body = extract_unreleased_body(text)
    if not body:
        raise ValueError(
            "CHANGELOG ## Unreleased is empty — add release notes before bumping, "
            f"or pass --no-changelog if {version!r} is already finalized"
        )
    after = text.split("## Unreleased", 1)[1]
    match = re.search(r"\n## \[", after)
    tail = after[match.start() + 1 :] if match else ""
    new_text = (
        text.split("## Unreleased", 1)[0]
        + "## Unreleased\n\n"
        + f"## [{version}] — {release_date}\n\n"
        + body
        + "\n\n"
        + tail
    )
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _changelog_added_summary(changelog_text: str, version: str) -> str:
    pattern = rf"## \[{re.escape(version)}\][^\n]*\n.*?### Added\n\n(.*?)(?=\n### |\n## \[|\Z)"
    match = re.search(pattern, changelog_text, re.DOTALL)
    if not match:
        return "See the changelog for highlights."
    lines = [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("- ")
    ]
    if not lines:
        return "See the changelog for highlights."
    summary = lines[0].lstrip("- ").strip()
    if summary.startswith("**") and "**" in summary[2:]:
        end = summary.index("**", 2)
        return summary[2:end]
    return summary[:120]


def write_release_doc(
    root: Path,
    version: str,
    release_date: str,
    *,
    previous_version: str | None,
) -> bool:
    path = root / "docs" / "releases" / f"v{version}.md"
    if path.is_file():
        return False
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    summary = _changelog_added_summary(changelog, version)
    prev = previous_version or "the previous tag"
    prev_link = f"v{previous_version}.md" if previous_version else "CHANGELOG.md"
    body = f"""# PyVELM v{version}

**Release date:** {release_date}

Release after **{prev}**: {summary}

---

## Highlights

Edit this page with user-facing highlights copied from [CHANGELOG](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md#{version.replace(".", "")}--{release_date}).

---

## Upgrade

```bash
pip install -U "pyvelm=={version}"
pyvelm db migrate
```

Regenerate typing stubs if you use ``make:stubs``:

```bash
pyvelm make:stubs
```

See [CHANGELOG](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md#{version.replace(".", "")}--{release_date}) for the full list.
"""
    path.write_text(body, encoding="utf-8")
    return True


def bump_readme(path: Path, version: str, release_date: str) -> bool:
    """Update root ``README.md`` latest-version link and ``pip install`` pin."""
    text = path.read_text(encoding="utf-8")
    anchor = version.replace(".", "")
    new = re.sub(
        r"\*\*Latest: \[v[\d.]+\]\([^)]+\)\*\*",
        (
            f"**Latest: [v{version}]"
            f"(https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md"
            f"#{anchor}--{release_date})**"
        ),
        text,
        count=1,
    )
    new = re.sub(
        r"pip install pyvelm==[\d.]+",
        f"pip install pyvelm=={version}",
        new,
        count=1,
    )
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def bump_docs_index(path: Path, version: str, release_date: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new = text
    new = re.sub(
        r"\*\*Latest release:\*\* \[v[^\]]+\]\(releases/[^)]+\.md\) — [^\n]+",
        f"**Latest release:** [v{version}](releases/v{version}.md) — "
        f"see [CHANGELOG](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md#{version.replace('.', '')}--{release_date}).",
        new,
        count=1,
    )
    new = re.sub(
        r"pip install pyvelm==[\d.]+",
        f"pip install pyvelm=={version}",
        new,
        count=1,
    )
    unreleased_row = (
        f"| [Unreleased](releases/unreleased.md) | "
        f"*(none yet after v{version})* |"
    )
    new = re.sub(
        r"\| \[Unreleased\]\(releases/unreleased\.md\) \| \*[^*]+\* \|",
        unreleased_row,
        new,
        count=1,
    )
    version_row = (
        f"| [v{version}](releases/v{version}.md) | "
        f"**{version}** — see release notes |"
    )
    if f"[v{version}](releases/v{version}.md)" not in new:
        new = new.replace(
            "| Version | Highlights |\n|---------|------------|\n",
            "| Version | Highlights |\n|---------|------------|\n"
            + version_row
            + "\n",
            1,
        )
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def bump_unreleased_doc(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new = re.sub(
        r"_No unreleased highlights yet — edit this page when features land on `main` after \*\*v[^*]+\*\*._",
        f"_No unreleased highlights yet — edit this page when features land on `main` after **v{version}**._",
        text,
        count=1,
    )
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def bump_roadmap(path: Path, version: str, release_date: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new = re.sub(
        r"\| \*\*Stable\*\* \| \*\*v[^|]+\*\* \([^)]+\) \|",
        f"| **Stable** | **v{version}** ({release_date}) |",
        text,
        count=1,
    )
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def bump_context(path: Path, version: str, release_date: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new = re.sub(
        r"^# Project context — pyvelm v[\d.]+",
        f"# Project context — pyvelm v{version}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    summary = ""
    changelog = path.parent / "CHANGELOG.md"
    if changelog.is_file():
        summary = _changelog_added_summary(
            changelog.read_text(encoding="utf-8"), version
        )
    highlight = (
        f"**v{version} (released {release_date})** — {summary} "
        f"See [docs/releases/v{version}.md](docs/releases/v{version}.md)."
    )
    if re.search(rf"\*\*v{re.escape(version)} \(released", new):
        if new == text:
            return False
        path.write_text(new, encoding="utf-8")
        return True
    new = re.sub(
        r"(# Project context — pyvelm v[\d.]+\n\nBuilding an Odoo-style ERP framework in Python.\n\n)",
        rf"\1{highlight}\n\n",
        new,
        count=1,
    )
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def bump_all(
    root: Path,
    version: str,
    release_date: str,
    *,
    changelog: bool = True,
    docs: bool = True,
) -> list[str]:
    version = parse_version(version)
    previous = read_pyproject_version(root)
    changed: list[str] = []

    if bump_pyproject(root / "pyproject.toml", version):
        changed.append("pyproject.toml")
    if bump_init(root / "pyvelm" / "__init__.py", version):
        changed.append("pyvelm/__init__.py")

    if changelog:
        if finalize_changelog(root / "CHANGELOG.md", version, release_date):
            changed.append("CHANGELOG.md")

    if docs:
        rel = write_release_doc(
            root,
            version,
            release_date,
            previous_version=previous if previous != version else None,
        )
        if rel:
            changed.append(f"docs/releases/v{version}.md")
        for rel_path, fn in (
            ("README.md", lambda p: bump_readme(p, version, release_date)),
            ("docs/index.md", lambda p: bump_docs_index(p, version, release_date)),
            ("docs/releases/unreleased.md", lambda p: bump_unreleased_doc(p, version)),
            ("ROADMAP.md", lambda p: bump_roadmap(p, version, release_date)),
            ("CONTEXT.md", lambda p: bump_context(p, version, release_date)),
        ):
            path = root / rel_path
            if path.is_file() and fn(path):
                changed.append(rel_path)

    remaining = check_versions(root)
    if remaining:
        raise RuntimeError("Version check failed after bump: " + "; ".join(remaining))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version",
        nargs="?",
        help="New semver version (X.Y.Z)",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Release date for CHANGELOG (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--no-changelog",
        action="store_true",
        help="Skip CHANGELOG finalization (only bump pyproject.toml and __init__.py)",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Skip README.md, docs/index.md, ROADMAP, CONTEXT, and release page",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify pyproject.toml and pyvelm.__version__ agree; exit 1 on mismatch",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    root = repo_root(args.root)

    if args.check:
        errors = check_versions(root)
        if errors:
            for err in errors:
                print(f"error: {err}", file=sys.stderr)
            return 1
        print(
            f"OK: pyproject.toml and pyvelm.__version__ = "
            f"{read_pyproject_version(root)}"
        )
        return 0

    if not args.version:
        parser.error("version is required unless --check is used")

    try:
        changed = bump_all(
            root,
            args.version,
            args.date,
            changelog=not args.no_changelog,
            docs=not args.no_docs,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not changed:
        print(f"No files changed (already at {args.version}?)")
        return 0

    print(f"Bumped to v{parse_version(args.version)}:")
    for name in changed:
        print(f"  - {name}")
    print()
    print("Next steps:")
    print(f'  git commit -am "Release v{args.version}"')
    print(f"  ./scripts/tag_release.sh {args.version}")
    print(f"  git push && git push origin v{args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
