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
| **Header logo height (px)** | Logo height in the admin shell sidebar (default 68 when 0; matches the 60px main header row plus padding) |
| **Show app name in header** | When off, only the logo (or default tile) shows in the sidebar / top bar |
| **Favicon URL** | Browser tab icon |
| **Primary color** | Accent palette (buttons, links, default logo tile) |
| **Font family** | UI typeface — pick from curated Google Fonts (empty = Inter; global default via `PYVELM_FONT_FAMILY`) |
| **Copyright** | Footer legal line |
| **Support email / URL** | Footer links |
| **Show powered by pyvelm** | Hide the small “Powered by pyvelm” line when off |
| **Navigation layout** | Shell chrome: `apps` (sidebar icons + top bar) or `sidebar` (3-level tree). Empty = use global `PYVELM_MENU_LAYOUT`. See [Navigation](navigation.md#per-company-override). |

Branding follows the **active company** cookie (`pyvelm_company`), same as theme accent.

## Environment variables (deploy-wide defaults)

Set before starting the server; company fields override these when filled in:

```bash
PYVELM_APP_NAME="Acme ERP"
PYVELM_APP_TAGLINE="Sign in to your workspace"
PYVELM_LOGO_URL="/api/attachment/12/download"
PYVELM_LOGO_URL_DARK="/api/attachment/14/download"
PYVELM_HEADER_LOGO_HEIGHT=48
PYVELM_SHOW_HEADER_BRAND_TEXT=0
PYVELM_FAVICON_URL="/api/attachment/13/download"
PYVELM_COPYRIGHT="© 2026 Acme Corp. All rights reserved."
PYVELM_SUPPORT_EMAIL="help@acme.example"
PYVELM_SUPPORT_URL="https://acme.example/support"
PYVELM_SHOW_POWERED_BY=0
PYVELM_FONT_FAMILY="Roboto"
```

Requires **base module 0.21.0+** (run **Apps → base → Sync** after upgrade).

Per-company **font family** (`font_family`) requires **base 0.32.0+**.

**Header logo height** and **show app name in header** require **base 0.33.0+**.

Per-company **navigation layout** (`menu_layout`) requires **base 0.31.0+**;
middleware is registered automatically via `base.web:register_routes`.

## API

Templates receive `brand`, `company_theme_style`, and font keys
(`company_font_stylesheet_url`, `company_font_style`, `company_font_family`)
from `pyvelm.branding.branding_context(env)`.
