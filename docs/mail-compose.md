# Email composer (`mail_compose` module)

A user-facing composer for sending email from any record: pick a
template (or write ad-hoc HTML), edit subject/body, add Cc / Bcc /
Reply-To and attachments, then send. The base mail queue + cron
dispatcher (see `pyvelm.mail`) does the actual SMTP delivery.

## Install

`mail_compose` ships in the wheel alongside `base` and `admin`.
Install it from **Apps** (depends on `base` and `admin`), or include
the module root when you boot your project:

```python
from pyvelm import BUILTIN_MODULE_ROOTS, loader
loader.load_and_install(BUILTIN_MODULE_ROOTS + [my_app_root], env)
```

The install hook grants `crud` to **User** and `crud` to **Admin** on
`mail.compose.message`.

## What you get

- **Multi-recipient send.** `To`, `Cc`, and `Bcc` accept a single
  address or a comma- / semicolon-separated list. The SMTP backend
  splits the list and addresses each envelope correctly. `Reply-To`
  is set as a header.
- **Templated rendering** against the bound record. Pick a
  `mail.template` whose `model` matches the composer's `model`; the
  **Apply template** action runs the template's Jinja against
  `object = <record>` and overwrites subject + body.
- **Auto-resolved `To`.** When the composer is launched from a
  record, it scans the record for `email` / `email_from` /
  `contact_email` / `work_email` / `login`, then one-hop Many2one
  paths (`partner_id.email`, `user_id.email`, `user_id.login`,
  `author_id.login`, `contact_id.email`). First non-empty wins.
- **Attachments.** A Many2many to `ir.attachment`. The SMTP backend
  reads each row's `fetch_content()` at dispatch time and adds it as
  a MIME part.
- **Save as template.** One click clones the current subject + body
  into a new `mail.template` bound to the same model. Operators
  rename / tweak the template afterwards.

## Composer from a record

Any record whose model inherits `MailThread` shows a chatter panel
on its form view. With `mail_compose` installed, the **Send email**
tab gains an **Open rich composer** link that launches the composer
in a floating `PvDialog`:

```text
Chatter → Send email → Open rich composer →
    PvDialog [mail.compose.message form] →
        Apply template / Save as template / Send
```

Send queues a row on `mail.message` with `state="outgoing"`; the
cron `mail.dispatch_outgoing` tick delivers it via SMTP (or the
console / disabled backend in dev).

## Programmatic send

```python
record.send_mail(
    template,
    to="ops@acme.example, billing@acme.example",
    cc="watch@acme.example",
    bcc="audit-log@acme.example",
    reply_to="noreply@acme.example",
    attachment_ids=[att1.id, att2.id],
)
```

Same multi-recipient + cc/bcc/reply_to shape on
`record.notify(body, recipient_email=..., cc=..., bcc=...)` for
log-and-send without a template.

## HTTP endpoints

| Method | URL                                                    | Purpose |
|--------|--------------------------------------------------------|---------|
| GET    | `/web/mail/compose/launch?model=&res_id=&template_id=` | Create draft + return form fragment |
| POST   | `/web/mail/compose/{id}/apply-template`                | Re-render template into subject/body |
| POST   | `/web/mail/compose/{id}/save-as-template`              | Clone draft into a new `mail.template` |
| POST   | `/web/mail/compose/{id}/send`                          | Queue + transition to `state="sent"` |

The launch endpoint is what the chatter link opens via
`window.PvDialog.open({url, title, onResult})`.

## SMTP configuration

Backend selection and credentials are unchanged from
[the base mail layer](api/mail.md):

```bash
PYVELM_MAIL_BACKEND=smtp
PYVELM_SMTP_HOST=smtp.gmail.com
PYVELM_SMTP_PORT=587
PYVELM_SMTP_USER=mybot@example.com
PYVELM_SMTP_PASSWORD=...
PYVELM_SMTP_FROM=mybot@example.com
PYVELM_SMTP_USE_TLS=1
```

The `console` backend (default in dev) prints To / Cc / Bcc / Reply-To
to stdout so you can verify the composer's output without a server.
