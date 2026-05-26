# Mail

Outgoing mail, chatter (`MailThread`), and email templates.

## Email templates (`mail.template`)

Admins manage templates under **Settings → Workflows → Email templates**.
Each template targets a model (`res.partner`, etc.) and stores a Jinja2
subject plus an **`Html`** body (sanitized on save). The editor has:

- **Write** — TipTap v3 ribbon toolbar (styles, font, lists, insert image, etc.)
- **HTML source** — CodeMirror 6 (language **html** or **jinja**), Jinja variable autocomplete (Ctrl+Space)
- **Preview** — sanitized HTML; optional **preview with record** via
  `POST /api/mail/templates/preview` and a record picker on the Preview tab

Bundled via npm into `/web/static/dist/mail_editor.js` — run
`npm install && npm run build:editor` after changing editor code. Prefer
**HTML source** for heavy `{{ object.* }}` editing; the Write tab may
normalize markup around placeholders.

**Insert variable** — searchable dropdown (type to search when the model has
more than 25 fields). Model list: `GET /api/mail/templates/models`; fields:
`GET /api/mail/templates/variables?model=…`.

Legacy Odoo syntax `${object.name}` is accepted.

From code on a `MailThread` record:

```python
partner.send_mail(template, to="user@example.com", extra={"ctx": {"token": "abc"}})
# or
template.send_mail(partner, to="user@example.com")
```

Rendered mail is queued on `mail.message` with `body_is_html=True` and
dispatched by the usual cron / `Message.dispatch_outgoing()`.

## `Html` field

Subclass of `Text`; values pass through `pyvelm/html_sanitizer.py` on write.
Renders with the HTML editor widget by default.

## API reference

::: pyvelm.mail

::: pyvelm.mail_template

::: pyvelm.html_sanitizer
