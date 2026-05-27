# File library (`file_manager` module)

A bundled library + picker for `ir.attachment` rows. Install the
module to get a **Files** app on the rail (a thumbnail kanban + a
sortable list), an upload page, and two field widgets that pick
existing files (or upload a new one inline) from any record form.

## Install

`file_manager` ships in the wheel alongside `base`/`admin`/`technical`.
Install it from **Apps**, or include the module root when you boot
your project. The install hook grants:

- **Admin** — full CRUD on `ir.attachment`.
- **User** — read on `ir.attachment` (so non-admins can pick from
  the library through the field widgets, even though they can't reach
  the management UI).

## Library

- **Files → Library** (`/web/views/file_manager/file_manager.file.kanban`)
  — thumbnail grid. Image MIME types render their bytes as the tile
  (via `/api/attachment/{id}/download`); everything else shows a
  MIME-icon tile.
- **Files → All files**
  (`/web/views/file_manager/file_manager.file.list`) — sortable
  table: name, MIME, size, owning record, public flag, uploaded-at.
  The **+ New** button jumps to the multipart upload page.

The kanban thumbnail is driven by a new `card(image=<field>)` slot
on the kanban builder; it expects the field to hold a URL. The
`file_manager` module extends `ir.attachment` with a computed
`thumbnail_url` Char that returns
`/api/attachment/{id}/download` for image MIMEs and an empty
string otherwise. Reuse the slot in your own kanbans by exposing a
Char field that resolves to an image URL.

## Upload page

`GET /web/files/upload` renders a simple multipart form (file input
+ Public checkbox). `POST /web/files/upload` accepts the form data,
loops the uploads through the same code path as
`/api/attachment/upload`, and redirects back to the library kanban.
Files arrive without `res_model` / `res_id`; the picker is the way
to attach them to a record later.

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
`/web/files/picker?accept=image/*` in `PvDialog` — a browseable
grid of existing files with:

- live name search (client-side over the library snapshot),
- mimetype filter — derived from the field spec's `accept` token,
- inline **Upload** button that POSTs to
  `/web/files/picker/upload` and selects the new row immediately.

Single-mode picks close the dialog on tile click; multi-mode picks
collect a selection and emit it via the **Use selected** footer
button. The dialog's `onResult` handler patches the field's hidden
input — Many2one stores one id, Many2many stores comma-separated
ids (the existing parent-form parser already accepts both shapes).

Display mode renders the chip (image MIMEs → thumbnail link;
everything else → a small file pill with download link). For empty
read-only fields it renders **No file**.

## HTTP endpoints

| Method | URL | Purpose |
|--------|-----|---------|
| GET    | `/web/files/upload` | Multipart upload page (Library "+ New" button lands here) |
| POST   | `/web/files/upload` | Process the upload + redirect to Library |
| GET    | `/web/files/picker?accept=&q=&multi=0\|1` | Picker dialog body |
| POST   | `/web/files/picker/upload` | Upload-from-dialog, returns the new row JSON |
| POST   | `/api/attachment/upload` | Existing record-bound upload (unchanged) |
| GET    | `/api/attachment/{id}/download` | Existing download endpoint (unchanged) |
| DELETE | `/api/attachment/{id}` | Existing delete (unchanged) |

## Storage

The picker / library reuse the existing storage stack
(`PYVELM_STORAGE_BACKEND=db|local`). Operators don't choose a backend
per upload — the configured backend wins for every file dropped via
the library or picker.
