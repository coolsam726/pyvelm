# Versioned documentation

The site is published with [mike](https://github.com/jimporter/mike) on the
`gh-pages` branch. Each **release tag** (`v*`) deploys a versioned subtree;
**latest** is the default alias (root redirect).

## When docs are built vs published

| Trigger | What runs |
|---------|-----------|
| Pull request to `main` | `mkdocs build --strict` only (CI gate, no publish) |
| Push tag `v*` (e.g. `v1.0.0`) | `mike deploy` → `gh-pages`, then GitHub Pages rebuild |
| `workflow_dispatch` | Same as a tag deploy (manual version input) |

Doc changes on `main` are **not** published until you cut a release tag (or run
the docs workflow manually). That keeps the version picker aligned with releases.

**GitHub Pages source** must be **Deploy from a branch → `gh-pages` / `(root)`**,
not “GitHub Actions” or `main`. If the live site shows an old flat build with no
version picker, fix Pages settings and run:

```bash
gh api -X POST repos/coolsam726/pyvelm/pages/builds
```

| URL | Meaning |
|-----|---------|
| [coolsam726.github.io/pyvelm/](https://coolsam726.github.io/pyvelm/) | Redirects to **latest** |
| `…/pyvelm/latest/` | Current stable docs |
| `…/pyvelm/1.0/` | PyVELM **1.0.x** docs (minor alias) |
| `…/pyvelm/0.26/` | Last **0.26.x** line (when deployed) |

Use the version picker in the header to switch.

## Local preview

```bash
pip install -e ".[docs]"

# Current tree (no version prefix — good for editing)
mkdocs serve

# Match a versioned deploy layout
mike serve
```

## Maintainer commands

After merging doc changes on `main`, cut a release tag. CI runs
`.github/workflows/docs.yml` and executes:

```bash
mike deploy --push --update-aliases <version> latest
mike set-default --push latest
```

Manual deploy (same as CI, from a clean `main` checkout):

```bash
git fetch origin main
git checkout main
pip install -e ".[docs]"
git config user.name "you"
git config user.email "you@example.com"

VERSION=1.0   # no leading v in mike paths
mike deploy --push --update-aliases "$VERSION" latest
mike set-default --push latest
```

Backfill an older release (e.g. **0.26** for `v0.26.2`) without moving **latest**:

1. Actions → **docs** → **Run workflow**
2. Set version to `0.26`, turn off **update latest**
3. Or locally:

```bash
git checkout v0.26.2
mike deploy --push 0.26   # do not pass latest if 1.0 should stay default
```

Validate links before tagging:

```bash
mkdocs build --strict
```

See [CONTRIBUTING.md](https://github.com/coolsam726/pyvelm/blob/main/CONTRIBUTING.md#documentation).
