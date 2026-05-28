# PyVELM

[![CI](https://github.com/coolsam726/pyvelm/actions/workflows/ci.yml/badge.svg)](https://github.com/coolsam726/pyvelm/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/coolsam726/pyvelm/graph/badge.svg)](https://codecov.io/gh/coolsam726/pyvelm)
[![PyPI version](https://img.shields.io/pypi/v/pyvelm)](https://pypi.org/project/pyvelm/)
[![Python](https://img.shields.io/pypi/pyversions/pyvelm)](https://pypi.org/project/pyvelm/)
[![Downloads](https://img.shields.io/pepy/dt/pyvelm?label=downloads)](https://pepy.tech/project/pyvelm)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-2563eb)](https://coolsam726.github.io/pyvelm/)
[![Changelog](https://img.shields.io/badge/changelog-CHANGELOG-64748b)](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPLv3-blue.svg)](https://github.com/coolsam726/pyvelm/blob/main/LICENSE)
[![GitHub Sponsors](https://img.shields.io/github/sponsors/coolsam726?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/coolsam726)

**Odoo's semantics. Laravel's ergonomics. Filament's craft — in a Tailwind-native
ERP shell that exists only here.**

**PyVELM** is a declarative Python ERP on PostgreSQL: recordsets and modules in the
Odoo tradition, developer and admin patterns borrowed from Laravel and Filament,
and a bespoke **Tailwind v4 + HTMX** interface—its own layout, widgets, and look &
feel—not Odoo's web client or Filament's Blade stack.

**Full documentation:** [coolsam726.github.io/pyvelm](https://coolsam726.github.io/pyvelm/)

The framework is **PyVELM**; the [PyPI](https://pypi.org/project/pyvelm/) package
and CLI stay `pyvelm` (lowercase).

## Install

```bash
pip install pyvelm
```

Greenfield app:

```bash
pipx install pyvelm
pyvelm init my_erp
```

## Hack on the repo

```bash
git clone https://github.com/coolsam726/pyvelm.git
cd pyvelm
python3 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env   # set PYVELM_DSN
.venv/bin/python examples/basic.py
```

Contributing, tests (`pip install -e ".[test]" && pytest`), local docs (`mkdocs serve`),
and releases: [CONTRIBUTING.md](CONTRIBUTING.md).
Maintainer notes: [CHANGELOG.md](CHANGELOG.md) · [CONTEXT.md](CONTEXT.md).

## Sponsor

PyVELM is maintained by [Sam Maosa](https://github.com/coolsam726).  
If it saves you time, consider [**sponsoring on GitHub**](https://github.com/sponsors/coolsam726).

## License

[LGPL-3.0-or-later](LICENSE) — Copyright (c) 2026 Sam Maosa.  
If you link against or modify PyVELM, see the license file for your obligations
(shared library / combined work terms).
