# Contributing

## Dev setup

```bash
git clone https://github.com/<org>/pyvelm
cd pyvelm
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[docs]"          # docs extras include mkdocs + mkdocstrings
cp .env.example .env              # set PYVELM_DSN (development database)
cp .env.testing.example .env.testing  # set PYVELM_DSN_TEST (throwaway test DB)
```

## Running the smoke test

`examples/basic.py` is the smoke suite. It drops and recreates the
schema on every run so it's safe to point at any Postgres database
you control:

```bash
python examples/basic.py
```

A clean run ends with the multi-company smoke prints. Anything
between them and the last `print` is a failure.

## Running the docs locally

```bash
mkdocs serve          # http://localhost:8000 with live reload
mkdocs build --strict # what CI runs
```

## Test coverage

CI runs `pytest --cov=pyvelm` with a **90%** floor (`fail_under` in
`pyproject.toml`; the measured tree is ~**91%** today). The gate covers
unit-testable framework code without gaming the metric.

What counts:

- All of `pyvelm/` except paths listed under `[tool.coverage.run] omit` in
  `pyproject.toml` (declarative addon files, ORM recordset runtime, view/menu
  builders, plus `web.py` / `render.py` and bundled module `web.py` registrars
  which are covered via HTTP smoke and route unit tests but omitted from the
  percentage so the gate reflects testable framework code).
- `examples/` is **not** measured; it drives integration tests only.

Integration tests (require `PYVELM_DSN_TEST`, loaded from `.env.testing`):

```bash
cp .env.testing.example .env.testing   # separate DB from PYVELM_DSN
pytest pyvelm/tests/test_http_smoke.py -v          # minimal HTTP smoke
PYVELM_RUN_FULL_BASIC=1 pytest pyvelm/tests/test_zzz_integration_smoke.py -v  # full examples/basic.py
```

Vellum slice tests under `pyvelm/modules/vellum/tests/` are collected via
`pyvelm/tests/test_vellum_all.py` (the `pyvelm.modules` package is not
importable as a normal namespace).

`document_layout` module tests: `test_document_layout_all.py` +
`test_document_layout_coverage.py`. Per-company navigation layout:
`test_menu_layout.py`.

Local coverage report:

```bash
pytest --cov=pyvelm --cov-report=term-missing
pytest pyvelm/tests/test_reports*.py --cov=pyvelm/reports --cov-report=term-missing
```

The reports package has dedicated unit tests (`test_reports.py`,
`test_reports_more.py`) plus DB integration (`test_reports_integration.py`).

`pyvelm.actions` (`ir.actions.server`) is covered by `pyvelm/tests/test_actions.py`
(requires `PYVELM_DSN` for integration cases).

CLI, console, cron, and schema autogen are covered by `test_cli_more.py`,
`test_console.py`, `test_cron.py`, and `test_db_autogen_more.py` (plus
`test_db_cli.py` and `test_db_autogen_constraints.py` for `db` subcommands).

Bundled addon hooks and console scaffolders: `test_modules_hooks.py`,
`test_console_commands.py`. Widgets: `test_datetime_pickers.py`,
`test_widgets_more.py`. Workflow core: `test_workflow.py`,
`test_workflow_more.py` (engine/schema/runtime; service/history are omitted
from the coverage gate).

Domain, mail, and fields: `test_domain.py`, `test_domain_more.py`,
`test_mail_compose.py` (address splitting), `test_mail_more.py`,
`test_fields_more.py`, plus `test_security.py` for Char coercion.

## Codecov (CI badge)

CI uploads `coverage.xml` on every push to `main`. The README badge stays
**unknown** until Codecov receives at least one successful upload.

One-time setup (repo maintainer):

1. Install the [Codecov GitHub app](https://github.com/apps/codecov) and
   add the **coolsam726/pyvelm** repository at [app.codecov.io](https://app.codecov.io).
2. Open the repo on Codecov → **Settings** → copy the **Repository upload token**.
3. On GitHub: **Settings → Secrets and variables → Actions** → create
   **`CODECOV_TOKEN`** with that value.
4. Re-run the latest **ci** workflow (or push a commit).

CI logs previously showed `Token required - not valid tokenless upload` because
v5 of the action requires an upload token for protected-branch pushes on most
orgs. After the secret is set, the badge at
`https://codecov.io/gh/coolsam726/pyvelm` should show a percentage on the next
green run.

## Cutting a release

pyvelm versions itself via three places that must agree:

- `pyproject.toml` → `[project].version`
- `pyvelm/__init__.py` → `__version__`
- The git tag → `v<X.Y.Z>`

The release workflow (`.github/workflows/release.yml`) verifies all
three at build time and refuses to publish if they diverge.

Steps:

1. **Update `CHANGELOG.md`.** Move the "Unreleased" entries under
   a new versioned heading. Note any breaking changes prominently.
2. **Bump the version in both Python files** (`pyproject.toml` and
   `pyvelm/__init__.py`).
3. **Commit + annotated tag** (message = CHANGELOG section):

   ```bash
   git commit -am "Release v0.2.9"
   ./scripts/tag_release.sh 0.2.9
   git push && git push origin v0.2.9
   ```

   `tag_release.sh` copies the `## [0.2.9]` block from `CHANGELOG.md`
   verbatim (including `### Added` / `### Fixed` headings). GitHub Release
   bodies use the same text via CI (`scripts/extract_changelog.py`).

4. **Watch the release workflow.** The tag push fires three jobs in
   sequence:
   - `build` — sdist + wheel + `twine check`.
   - `publish-pypi` — uploads to PyPI via OIDC trusted publishing.
     No API token; configure once on the PyPI project page.
   - `github-release` — publishes a GitHub Release with the wheel +
     sdist attached and **release notes from CHANGELOG.md** (not the
     auto-generated commit list).

   To fix an existing release body after the fact:

   ```bash
   ./scripts/github_release.sh 0.2.8
   ```
5. **Sanity-check** by installing from PyPI in a fresh venv:

   ```bash
   pipx install pyvelm==<X.Y.Z>
   pyvelm init demo && cd demo
   docker compose up --build
   ```

### One-time PyPI setup

The OIDC publishing path needs the PyPI project to trust this
repo's release workflow. After your first manual upload (or by
registering the package name first), open the project's
"Manage" → "Publishing" page on PyPI and add a trusted publisher:

| Field | Value |
|---|---|
| Owner | `<your-gh-org>` |
| Repository name | `pyvelm` |
| Workflow filename | `release.yml` |
| Environment name | `pypi` |

After that, every tagged push publishes without a stored token.

### Pre-releases (TestPyPI)

For dry-runs, add a TestPyPI trusted publisher on
`https://test.pypi.org/` with the same fields, then publish a tag
like `v0.2.0rc1`. The current workflow doesn't split between
TestPyPI and PyPI — when you want pre-release support, extend the
`publish-pypi` job with an `if: contains(github.ref, 'rc')` branch
pointing at TestPyPI.

## Pull-request etiquette

- Each commit should land green on the smoke test and the strict
  mkdocs build.
- Keep diffs focused. The project history is "one commit per
  shippable slice" — a feature, a fix, or a refactor; not a mix.
- Commit messages follow a paragraph-first format: a 50-char-ish
  subject, a blank line, then prose explaining *why* the change
  was made. The PR title becomes the merge commit's subject.
- No `Co-Authored-By:` trailers on pyvelm commits.

## Where things live

| Surface | Path |
|---|---|
| Framework code | `pyvelm/` |
| Bundled modules (`base`, `admin`) | `pyvelm/modules/` |
| Scaffold templates | `pyvelm/scaffolds/` |
| Example addons (partners, crm, …) | `examples/modules/` |
| Demo seed module | `examples/modules_demo/demo/` |
| Smoke test | `examples/basic.py` |
| User-guide docs | `docs/` |
| API reference stubs | `docs/api/` |
| Deployment artefacts | `Dockerfile`, `docker-compose.yml`, `gunicorn_conf.py` |
| Workflows | `.github/workflows/` |
