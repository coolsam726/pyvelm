"""Map a file's mimetype / name to a coarse icon key.

The file manager renders a type-specific glyph for non-image files
(PDF, Word, Excel, archives, …). Keeping the classification here —
top-level and pure — means both the Python row builder and the unit
tests can use it without importing the web layer, and the matching
SVGs live in one JS map (``window.pvFileIcon``).
"""

from __future__ import annotations

# mimetype (exact) → key
_EXACT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/json": "json",
    "application/ld+json": "json",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "doc",
    "application/vnd.oasis.opendocument.text": "doc",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xls",
    "application/vnd.oasis.opendocument.spreadsheet": "xls",
    "text/csv": "xls",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt",
    "application/vnd.oasis.opendocument.presentation": "ppt",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/x-tar": "zip",
    "application/x-7z-compressed": "zip",
    "application/x-rar-compressed": "zip",
    "application/vnd.rar": "zip",
    "application/gzip": "zip",
    "application/x-bzip2": "zip",
}

# filename extension → key (fallback when the mimetype is generic /
# missing, e.g. octet-stream uploads).
_EXT: dict[str, str] = {
    "pdf": "pdf",
    "json": "json",
    "doc": "doc", "docx": "doc", "odt": "doc", "rtf": "doc",
    "xls": "xls", "xlsx": "xls", "ods": "xls", "csv": "xls",
    "ppt": "ppt", "pptx": "ppt", "odp": "ppt",
    "zip": "zip", "tar": "zip", "gz": "zip", "tgz": "zip",
    "7z": "zip", "rar": "zip", "bz2": "zip",
    "txt": "text", "md": "text", "log": "text",
    "mp3": "audio", "wav": "audio", "ogg": "audio", "flac": "audio", "m4a": "audio",
    "mp4": "video", "mov": "video", "webm": "video", "mkv": "video", "avi": "video",
}


def file_icon_key(mimetype: str | None, filename: str | None = None) -> str:
    """Return a coarse icon key for a file.

    Image MIMEs return ``"image"`` (the manager shows the real
    thumbnail for those, not a glyph). Everything else maps to one of
    ``pdf / doc / xls / ppt / json / text / zip / audio / video`` or
    the generic ``"file"`` fallback.
    """
    mt = (mimetype or "").lower().split(";", 1)[0].strip()
    if mt.startswith("image/"):
        return "image"
    if mt in _EXACT:
        return _EXACT[mt]
    if mt.startswith("text/"):
        return "text"
    if mt.startswith("audio/"):
        return "audio"
    if mt.startswith("video/"):
        return "video"
    # Fall back to the filename extension for generic / missing MIMEs.
    name = (filename or "").lower()
    if "." in name:
        ext = name.rsplit(".", 1)[1]
        if ext in _EXT:
            return _EXT[ext]
    return "file"
