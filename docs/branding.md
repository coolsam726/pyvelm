# White-label branding

Customize how the UI looks for each company (or globally via environment variables).

## Per company

**Admin → Companies →** open a company → **Branding & white-label**:

| Field | Effect |
|-------|--------|
| **Application name** | Sidebar, top bar, browser title, login heading |
| **Tagline** | Login subtitle |
| **Logo URL (light)** | Sidebar / login in light mode |
| **Logo URL (dark)** | Logo in dark mode; if empty, the light logo is used |
| **Favicon URL** | Browser tab icon |
| **Primary color** | Accent palette (buttons, links, default logo tile) |
| **Copyright** | Footer legal line |
| **Support email / URL** | Footer links |
| **Show powered by pyvelm** | Hide the small “Powered by pyvelm” line when off |

Branding follows the **active company** cookie (`pyvelm_company`), same as theme accent.

## Environment variables (deploy-wide defaults)

Set before starting the server; company fields override these when filled in:

```bash
PYVELM_APP_NAME="Acme ERP"
PYVELM_APP_TAGLINE="Sign in to your workspace"
PYVELM_LOGO_URL="/api/attachment/12/download"
PYVELM_LOGO_URL_DARK="/api/attachment/14/download"
PYVELM_FAVICON_URL="/api/attachment/13/download"
PYVELM_COPYRIGHT="© 2026 Acme Corp. All rights reserved."
PYVELM_SUPPORT_EMAIL="help@acme.example"
PYVELM_SUPPORT_URL="https://acme.example/support"
PYVELM_SHOW_POWERED_BY=0
```

Requires **base module 0.21.0+** (run **Apps → base → Sync** after upgrade).

## API

Templates receive `brand` and existing `company_theme_style` from `pyvelm.branding.branding_context(env)`.
