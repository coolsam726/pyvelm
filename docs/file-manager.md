# File library (`file_manager` module)

A bundled library + picker for `ir.attachment` rows. Install the
module to get a **Files** app on the rail with a Drive-style library
(folder tree + thumbnail grid + selection + details slide-over + bulk
actions), a Properties page that surfaces real metadata (size,
dimensions for images, owner, folder breadcrumb), and two field
widgets that pick existing files from any record form.

## Install

`file_manager` ships in the wheel alongside `base` / `admin` /
`technical`. Install it from **Apps**, or include the module root
when you boot your project.

The install hook grants:

- **Admin** — full CRUD on `ir.attachment` and `res.attachment.folder`.
- **User** — read on `ir.attachment` and `res.attachment.folder` (so
  non-admins can pick files via the widgets and browse folders even
  when they can't manage them).

## Library (Drive-style shell)

**Files → Library** opens `/web/files/library`: a three-column shell
modelled on Nautilus / Windows Explorer / Google Drive.

| Column | What's there |
|--------|--------------|
| Left (tree) | **All files**, **Unfiled** (no folder), and the folder tree (nested via `parent_id`). Click a node to filter the grid. Drag a tile onto a node to move. **New subfolder** is available via the per-row **+** button (hover) or the folder right-click menu. |
| Centre (grid) | Server-rendered kanban grid for the current folder filter (reuses the standard kanban renderer). Clicking a file tile selects it and opens the details panel. The centre header also includes an **Upload** button that opens an inline upload dialog (no navigation away). |
| Right (details) | Slide-over Properties panel — appears when a tile is selected; mirrors the full Properties page. |

Non-image files show a tinted type glyph (`pvFileIcon`: pdf / doc /
xls / ppt / json / text / zip / audio / video / fallback) instead of a
broken thumbnail. On small screens every grid collapses to a single
column for legibility.

Folder creation uses the library’s create endpoint (`POST /web/files/folders`)
with `parent_id` set to the folder you chose (or `null` for top level).

### Selection model

- **Click** a tile → single-select + open the details panel.
- **Shift-click** a second tile → range fill over the currently
  visible order (server publishes the order so range stays
  deterministic across pagination).
- **Ctrl/Cmd-click** → toggle the tile in / out of the selection.
- The selection clears when you click the toolbar's ✕ or navigate.

### Bulk actions

Once at least one tile is selected, a sticky action bar appears at
the top of the centre column:

| Action | What happens |
|--------|--------------|
| Download | One file → direct `GET /api/attachment/{id}/download`. Two or more → hidden-form `POST /web/files/bulk/download` that streams a `.zip` (URL-typed rows are skipped with a `X-PV-Skipped` response header). |
| Toggle public | `POST /web/files/bulk/public` flips every selected row to `public=true`. |
| Delete | Confirms via `pvConfirm`, then `POST /web/files/bulk/delete` (204 on success). |

### Context menu

Right-clicking a tile opens a floating menu at the cursor: **Open
details**, **Properties page**, **Download**, **Toggle public**,
**Delete**. The same shortcuts are available on the action bar when
multiple files are selected.

### Drag-and-drop into folders

Tiles set `draggable="true"`. The drag payload is the current
selection if non-empty, otherwise just the dragged tile. Dropping
onto a tree node (or **Unfiled**) `POST`s `/web/files/move` to
update `folder_id` on every dragged row.

## Properties page

`/web/files/{id}/properties` is a Filament-shaped two-column page:

- **Left** — large preview. Image MIMEs render
  `<img src="/api/attachment/{id}/download">` in a 4:3 frame.
  Everything else shows a centred MIME-family icon + extension badge.
- **Right** — folder breadcrumb, metadata grid (Name, Filename,
  Type, Size, Dimensions, Created, Updated, Linked record, Storage,
  Public), and big **Download / Open linked record / Delete**
  action buttons.

**Image dimensions** are computed at render time by
`pyvelm.image_meta.read_image_dimensions` — a stdlib-only header
parser for PNG / JPEG / GIF / WebP. Other
image formats fall through to `—`. No schema column; no Pillow
dependency.

The same template body renders as a fragment at
`/web/files/{id}/properties_panel` for the right-side slide-over
in the Library shell — keeping "what shows in the panel" and "what
shows on the full page" in lockstep.

## Folders

`res.attachment.folder` is a hierarchical model (self M2o on
`parent_id` with `ondelete="RESTRICT"`). Folder rows carry `name`,
`sequence`, an optional `color`, and a computed `display_name` that
walks the parent chain into a slash breadcrumb (`Marketing / Logos
/ 2026`, depth-capped at 32 to defuse cycles).

`ir.attachment.folder_id` (Many2one with `ondelete="SET NULL"`) is
the link. `NULL` is the "Unfiled" bucket — every attachment created
by the chatter / picker / record-bound paths lands there by default.

Deletion guard: `DELETE /web/files/folders/{id}` returns **409
Conflict** when the folder still has children or attachments — empty
it first.

### Company scoping

The whole library is **per-company**. `res.attachment.folder` sets
`_company_scoped = True`, so the framework auto-injects a `company_id`
and filters every `search` by `env.company_id` — folders created under
one company are invisible to another. `ir.attachment` is shared
(avatars, mail, reports), so it stays cross-company; file_manager adds
a *nullable* `company_id` Many2one (not `_company_scoped`) and the
library / picker / tree queries scope to the active company explicitly
via `_library_company_domain`. Attachments are stamped with
`env.company_id` on upload and on copy. System attachments with no
company simply don't surface in a company-scoped library view.

## File-picker widgets

Declare the field as a Many2one (single) or Many2many (multi) to
`ir.attachment`, then opt into the picker with `widget="file"` /
`widget="files"`:

```python
from pyvelm import BaseModel, Char, Many2many, Many2one


class Brochure(BaseModel):
    _name = "marketing.brochure"

    title = Char(required=True)
    cover_id = Many2one("ir.attachment", string="Cover image")
    asset_ids = Many2many("ir.attachment", string="Assets")
```

```python
form_view(
    "brochure.form", "marketing.brochure",
    sections=[
        section("identity", "Brochure", ["title"]),
        section("media", "Media", [
            field("cover_id", widget="file", accept="image/*"),
            field("asset_ids", widget="files", accept="application/pdf,image/*"),
        ]),
    ],
)
```

Edit mode renders a chip list of already-picked attachments plus a
**Pick a file** button. The button opens
`/web/files/picker?accept=image/*` in `PvDialog` — a searchable tile grid
of existing files, with an optional mimetype filter derived from the
field spec’s `accept`.

Implementation notes (why the picker works inside a dialog):

- The picker’s config is carried in a `data-pv-cfg` attribute (JSON),
  and the component reads it with `JSON.parse($el.dataset.pvCfg)`.
- The app re-initializes Alpine on HTMX swaps (dialog bodies) so the
  picker mounts reliably without relying on `<script>` execution inside
  swapped fragments.

The picker also offers an inline **Upload** button that POSTs to
`/web/files/picker/upload` and selects the new row immediately.

Single-mode picks close the dialog on tile click; multi-mode picks
collect a selection and emit it via the **Use selected** footer
button. The dialog's `onResult` handler patches the field's hidden
input — Many2one stores one id, Many2many stores comma-separated
ids (the existing parent-form parser already accepts both shapes).

Display mode renders the chip (image MIMEs → thumbnail link;
everything else → a small file pill with download link). For empty
read-only fields it renders **No file**.

### `widget="file_url"` — pick into a URL column

`widget="file"` / `widget="files"` need a `Many2one` / `Many2many`
to `ir.attachment`. Many models instead carry an image as a plain
**URL `Char`** — company branding is the canonical case
(`res.company.logo_url`, `logo_url_dark`, `favicon_url`). For those,
use `widget="file_url"`:

```python
section("branding", "Branding & white-label", [
    field("logo_url", widget="file_url"),
    field("logo_url_dark", widget="file_url"),
    field("favicon_url", widget="file_url"),
])
```

It renders a preview thumbnail, a **Pick from library** button, a
manual URL input (for external links), and a **Clear** action. On
pick it opens the same `/web/files/picker?accept=image/*` dialog,
then:

1. flips the chosen attachment **public** (`POST /web/files/bulk/public`)
   — branding logos / favicons are served on unauthenticated pages
   (login, public shell), so they must be readable without a session;
2. stores `/api/attachment/{id}/download` into the `Char`.

`accept` defaults to `image/*`; override via
`field("doc_url", widget="file_url", accept="application/pdf")`. The
widget reads its config from a per-element `data-pv-cfg` attribute,
so several instances on one form (light logo, dark logo, favicon)
don't clobber each other.

This is the bundled, working example of the library's picking flow —
open **Settings → Companies → (a company) → Branding** to try it.

## Uploading into a folder

1. **Click the folder** in the left tree (e.g. **Marketing**) so the
   grid shows only that folder's files.
2. Click **Upload** (in the library page header or the centre header) —
   an inline dialog opens titled **Upload to Marketing**.
3. Pick files and confirm — they are stored with `folder_id` set to
   that folder.

If you upload while on **All files**, files go to **Unfiled**
(`folder_id` empty). You can move them later by dragging tiles onto a
folder in the tree.

The full-page `GET /web/files/upload?folder_id=…` route still exists for
direct links.

## HTTP endpoints

| Method | URL | Purpose |
|--------|-----|---------|
| GET    | `/web/files/library?folder_id=&q=&page=` | Drive-style shell (folder tree + grid + details). |
| GET    | `/web/files/upload_panel?folder_id=` | Upload fragment (legacy/optional; library now uses an inline upload dialog). |
| GET    | `/web/files/upload?folder_id=` | Full-page multipart upload (optional). |
| POST   | `/web/files/upload` | Process full-page upload + redirect to Library. |
| GET    | `/web/files/picker?accept=&q=&multi=0\|1` | Picker dialog body (used by `widget="file"` / `widget="files"`). |
| GET    | `/web/files/picker/browse` | Legacy/unused by current picker UI (kept for compatibility). |
| POST   | `/web/files/picker/upload` | Upload-from-dialog (returns row JSON). |
| GET    | `/web/files/{id}/properties` | Full Properties page. |
| GET    | `/web/files/{id}/properties_panel` | Properties fragment for the slide-over. |
| GET    | `/web/files/tree` | Folder list + per-folder counts JSON. |
| POST   | `/web/files/folders` | Create a folder (`{name, parent_id?}`). |
| PATCH  | `/web/files/folders/{id}` | Rename / move folder; rejects cycles. |
| DELETE | `/web/files/folders/{id}` | 204 if empty; 409 otherwise. |
| POST   | `/web/files/move` | Bulk move (`{attachment_ids, folder_id\|null}`). |
| POST   | `/web/files/bulk/download` | Stream a ZIP of selected ids. |
| POST   | `/web/files/bulk/delete` | Bulk delete. |
| POST   | `/web/files/bulk/public` | Bulk set `public=true|false`. |
| POST   | `/api/attachment/upload` | Existing record-bound upload (unchanged). |
| GET    | `/api/attachment/{id}/download` | Existing download endpoint (unchanged). |
| DELETE | `/api/attachment/{id}` | Existing delete (unchanged). |

## Storage

The picker / library reuse the existing storage stack
(`PYVELM_STORAGE_BACKEND=db|local`). Operators don't choose a backend
per upload — the configured backend wins for every file dropped via
the library or picker.

## Migration notes (0.1 → 0.3)

- **Base bumped to 0.29.0** — migration `0_28_to_0_29.py` adds the
  nullable `ir_attachment.folder_id` column. Schema autogen covers
  fresh installs; the explicit `ALTER TABLE … ADD COLUMN IF NOT
  EXISTS` in the migration is a safety net for databases that update
  base before re-installing file_manager.
- **Base bumped to 0.30.0** — migration `0_29_to_0_30.py` adds the
  nullable `ir_attachment.company_id` column (same safety-net `ALTER`).
  No backfill: existing attachments stay company-less and simply don't
  appear in a company-scoped library view.
- **file_manager bumped to 0.3.0** — install hook grants Admin CRUD +
  User read on `res.attachment.folder` (now `_company_scoped`) in
  addition to the existing `ir.attachment` grants.
- **Existing attachments** stay in the "Unfiled" bucket
  (`folder_id IS NULL`). No data backfill needed.
- The legacy Library menu entry used to point at the bare kanban view;
  it now points at the new `/web/files/library` shell. **Re-sync** the
  module via Apps → Sync (or restart the server) so the menu URL
  updates.
