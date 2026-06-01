# Versioned documentation

The site is published with [mike](https://github.com/jimporter/mike) on the
`gh-pages` branch. Each **release tag** (`v*`) deploys a versioned subtree;
**latest** is the default alias (root redirect).

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

Backfill an older release from its tag (optional):

```bash
git checkout v0.26.2
mike deploy --push --update-aliases 0.26 latest   # omit --update-aliases to keep latest on 1.0
```

Validate links before tagging:

```bash
mkdocs build --strict
```

See [CONTRIBUTING.md](https://github.com/coolsam726/pyvelm/blob/main/CONTRIBUTING.md#documentation).
