# Deploying pyvelm

The repo ships a multi-stage `Dockerfile`, a `gunicorn_conf.py`, and
a `docker-compose.yml` that brings up Postgres + an app worker + a
dedicated cron worker. Bring the whole stack up with one command:

```bash
cp .env.example .env       # adjust passwords for non-toy use
docker compose up --build
# → http://localhost:8000/login   (admin / admin)
```

The bundled demo module seeds ~20 partners + 15 CRM leads so the
UI is populated on first boot.

## How the image is built

The `Dockerfile` has two stages:

1. **`node:20-alpine`** — runs `npm install` + `npm run build` to
   compile Tailwind + Flowbite into `pyvelm/static/dist/pyvelm.css`
   and vendor `flowbite.min.js` next to it.
2. **`python:3.13-slim`** — installs the Python package +
   `gunicorn` + `uvicorn[standard]`, copies the source, copies the
   built CSS from stage 1, and runs as a non-root `pyvelm` user.

The container's `CMD` is `gunicorn -c gunicorn_conf.py app.serve:app` (or
`examples.serve:app` in this repo). Set **`PYVELM_ENV=production`** in
compose (the default) so API docs are hidden and session cookies get the
`Secure` flag.

| variable | default | what it does |
|---|---|---|
| `PYVELM_ENV` | `production` in Docker; `development` for `python -m app.serve` | Runtime mode — docs, cookies, log level |
| `GUNICORN_BIND` | `0.0.0.0:8000` | Address gunicorn binds to |
| `GUNICORN_WORKERS` | `2 × CPU + 1` | Number of worker processes |
| `GUNICORN_TIMEOUT` | `30` | Per-request timeout (seconds) |
| `GUNICORN_FORWARDED_ALLOW_IPS` | `127.0.0.1` | IP / CIDR of trusted proxy for `X-Forwarded-*` |

### Development inside Docker

Scaffolded projects ship `docker-compose.dev.yml`. Merge it for hot reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

That sets `PYVELM_ENV=development` and runs `python -m app.serve --reload`
instead of gunicorn.

## Scaling out

A few things shift when you run multiple workers or sit behind a
reverse proxy:

- **`/login` rate limit is per-worker.** The bundled `docker-compose.yml`
  pins `GUNICORN_WORKERS=1` for that reason. For real production
  put a shared rate limiter in front (nginx `limit_req`, Cloudflare
  WAF) and treat the per-worker count as a backstop.
- **Real client IPs.** Behind a reverse proxy the framework needs
  `X-Forwarded-For` to see the user's IP — otherwise every request
  buckets under the proxy's address and a single legitimate user's
  retries can lock everyone behind that proxy out. Set
  `GUNICORN_FORWARDED_ALLOW_IPS` to the proxy's IP/CIDR.
- **Connection pooling.** Each gunicorn worker opens its own
  `psycopg_pool.ConnectionPool` — set Postgres's `max_connections`
  to at least `workers × pool_max_size`, plus headroom for psql
  sessions and migrations.
- **First-boot install.** Run **`pyvelm db migrate`** once per deploy before
  workers start (see [Migrations](migrations.md)). Scaffolded
  `docker-compose.yml` includes a one-shot `migrate` service; `app` waits for
  it. Both migrate and `app/serve.py` boot with the same default: **base** and
  **admin** on a fresh database. Install other modules from **Apps**, or use
  **`pyvelm db migrate --all`** / **`--module`** when you need a CLI install.
- **Static assets.** `/web/static/*` is served by Starlette today —
  fine for small deployments. Production setups should put a CDN or
  the reverse proxy in front, serving `pyvelm/static/dist/`
  directly.

## The cron worker

`pyvelm cron` is the background runner. It boots the registry once,
opens a connection pool, and ticks `CronJob.run_due` every N
seconds — which fires due cron jobs, including the built-in mail
dispatcher. The compose file ships a `cron` service that runs it
alongside the app.

```yaml
cron:
  command: ["pyvelm", "cron"]
  environment:
    PYVELM_DSN: postgresql://…
    PYVELM_MODULE_ROOTS: /app/examples/modules:/app/examples/modules_demo
    PYVELM_CRON_INTERVAL: 60
```

| variable / arg | default | what it does |
|---|---|---|
| `PYVELM_DSN` | (required) | SQLAlchemy URL — `postgresql+psycopg://…` (production) or `sqlite:///…` (dev/CI) |
| `PYVELM_DATABASES` | — | Optional multi-tenant catalog (`key=dsn,…` or JSON); see [multi-database.md](multi-database.md) |
| `PYVELM_MODULE_ROOTS` | (required) | Colon-separated module dirs |
| `PYVELM_CRON_INTERVAL` / `--interval` | `60` | Seconds between ticks |
| `--roots` | env var | Override the module-root list inline |

The CLI prepends `pyvelm.BUILTIN_MODULE_ROOTS` automatically — the
env var only needs to list your app-side addons. SIGTERM / SIGINT
flip a shutdown flag; the loop drains the current tick and exits
gracefully.

!!! warning "One cron worker per database"
    `CronJob.run_due` does a plain SELECT-then-UPDATE without
    row-level locking. Running multiple cron workers will
    occasionally double-fire a job at its exact due time. The
    compose `cron` service is pinned at `replicas: 1` for that
    reason. `SELECT … FOR UPDATE SKIP LOCKED` is on the list to
    make multi-worker safe.

## Sending email

`mail.message` doubles as a log table and an outgoing-mail queue.
Rows that set `recipient_email` (with `state="outgoing"`) get
drained by the dispatcher cron — seeded automatically by the base
module — every minute.

The dispatcher hands each row to a configurable backend:

| `PYVELM_MAIL_BACKEND` | what it does |
|---|---|
| `console` (default) | Log the would-be send to stdout. Dev / CI. |
| `disabled` | Silently mark every row `sent` without contacting any server. |
| `smtp` | Talk SMTP — see vars below. |

For `smtp` mode set:

```bash
PYVELM_SMTP_HOST=smtp.example.com
PYVELM_SMTP_PORT=587
PYVELM_SMTP_USER=…
PYVELM_SMTP_PASSWORD=…
PYVELM_SMTP_FROM=noreply@example.com
PYVELM_SMTP_USE_TLS=1               # STARTTLS; set to 0 to skip
```

State transitions are terminal — once a row hits `sent` or
`failed` the dispatcher leaves it alone. `failed` rows capture the
exception text in `error` for operator triage; restart delivery
manually by flipping `state` back to `"outgoing"` (and clearing
`error`).

To queue an outgoing message from app code:

```python
partner.notify(
    "Welcome aboard, Alice!",
    recipient_email="alice@example.test",
    subject="Welcome",
)
```

`MailThread.notify(...)` writes a `mail.message` with all the right
defaults so the next dispatcher tick picks it up. To log without
sending, use `partner.message_post("…")` instead.

## Auth & security

The browser flow has three guard layers — they sit one above the
other in the request stack.

### CSRF: double-submit cookie

A `CsrfMiddleware` mints a `pyvelm_csrf` cookie on the first GET
that doesn't carry one (random 32-byte token, `SameSite=Lax`,
**not** `HttpOnly` because the layout JS reads it). Every unsafe
method (POST, PUT, PATCH, DELETE) must echo the value back as
either an `X-CSRF-Token` header or a `_csrf` form field. The two
paths are equivalent; pick whichever fits the call site.

The middleware skips the check in two cases:

1. **HTTP Basic auth** — an attacker can't forge `Authorization:
   Basic …` from a cross-origin page, so the protection buys
   nothing for machine clients calling the API with inline
   credentials.
2. **Cookie-less requests** — nothing to protect if no cookies are
   present.

Template / JS plumbing is automatic:

- HTMX `configRequest` listener injects the header on every HTMX
  request. Save / delete buttons that use `hx-post` / `hx-delete`
  pick it up transparently.
- `DOMContentLoaded` (and post-swap) handler scans every
  `<form method="post">` and appends a hidden `_csrf` input pulled
  from the cookie. Logout + the password-change form ride that
  path; no per-template CSRF threading is required.

### Login rate limit

`/login` enforces a **5 attempts per 5 minutes** sliding window
keyed by client IP. The 6th attempt returns 429 with a
`Retry-After` header. Both successful and failed attempts count so
a brute-forcer can't probe silently.

The window is per-worker (see [Scaling out](#scaling-out)).

### Self-service password change

`GET /web/account/password` renders a three-input form (current /
new / confirm). The POST verifies the current password via bcrypt,
checks the new is at least 6 characters and matches the
confirmation, and rejects new-equals-current. The new value is
written through the `Password` field, which re-hashes on store.

Admins can change anyone else's password via the existing
`res.users` form, which writes the same `Password` field directly.

Session tokens stay valid until the cookie expires — rotating them
on password change is on the list.

## Optional server tools

| Tool | Used by | Install |
|------|---------|---------|
| **wkhtmltopdf** | [`document_layout`](document-layout.md) PDF routes (`/report/pdf/…`) | `apt-get install wkhtmltopdf` (Debian/Ubuntu) or equivalent |

HTML preview routes work without wkhtmltopdf; only PDF download returns **503**
when the binary is missing.

## Open work

A few rough edges worth flagging:

- Field-level validation feedback in the **inline-row** edit form
  surfaces today as a toast; per-cell red borders (the form-view
  treatment) would need a small `errors` layer in the row renderer.
- The arch resolver re-reads `ir.ui.view` on every request — fine
  for typical loads, but a per-`(module, name)` cache is cheap and
  obvious to add when load matters.
- Pagination is `LIMIT/OFFSET` and the page bar reports `count`
  from `search_count`. No cursor abstraction.
