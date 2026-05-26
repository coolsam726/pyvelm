# Mail

Outgoing mail, chatter (`MailThread`), and email templates.

## Email templates (`mail.template`)

Admins manage templates under **Settings → Workflows → Email templates**.
Each template targets a model (`res.partner`, etc.) and stores a Jinja2
subject + HTML body. The **body** field editor has **Write** (TipTap),
**HTML source** (CodeMirror 6), and **Preview** tabs. Bundled via npm into
`/web/static/dist/mail_editor.js` — run `npm install && npm run build:editor`
after changing editor code. Use HTML source for Jinja
placeholders (`object`, `user`, `company`, `ctx`). Legacy Odoo syntax
`${object.name}` is accepted.

From code on a `MailThread` record:

```python
partner.send_mail(template, to="user@example.com", extra={"ctx": {"token": "abc"}})
# or
template.send_mail(partner, to="user@example.com")
```

Rendered mail is queued on `mail.message` with `body_is_html=True` and
dispatched by the usual cron / `Message.dispatch_outgoing()`.

## API reference

::: pyvelm.mail

::: pyvelm.mail_template
