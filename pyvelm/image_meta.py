"""Pure-stdlib image-header parsing for PNG / JPEG / GIF / WebP.

Used by the file_manager Properties page to surface image dimensions
without taking a dependency on Pillow. We only need width × height,
which lives in the file header (well under 100 bytes for every format
we cover here), so the cost of parsing is negligible even for the
caller that's already fetched the bytes.

Any exception, signature mismatch, or truncated input → ``None``.
The caller renders ``—`` in that case so a single corrupt file never
breaks the Properties page.
"""

from __future__ import annotations

import struct


def read_image_dimensions(data: bytes, mimetype: str) -> tuple[int, int] | None:
    """Return ``(width, height)`` for a known image format or ``None``.

    ``mimetype`` dispatch is intentionally narrow — only the formats
    whose header layout is fully spec-defined and that stdlib can read
    without third-party libs. SVG, TIFF, BMP, HEIC, etc. fall through
    to ``None``.
    """
    if not data:
        return None
    mt = (mimetype or "").lower().split(";", 1)[0].strip()
    try:
        if mt == "image/png":
            return _png(data)
        if mt in ("image/jpeg", "image/jpg", "image/pjpeg"):
            return _jpeg(data)
        if mt == "image/gif":
            return _gif(data)
        if mt == "image/webp":
            return _webp(data)
    except Exception:  # noqa: BLE001 — any parse failure → None
        return None
    return None


# ---- PNG --------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE:
        return None
    # After the 8-byte signature: 4-byte length + 4-byte type ("IHDR")
    # at offset 12, followed by 4 bytes width + 4 bytes height
    # (big-endian uint32). IHDR is mandatory + must come first.
    if data[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) if (w > 0 and h > 0) else None


# ---- JPEG -------------------------------------------------------------

# SOF (Start of Frame) markers carrying width/height. Excludes SOF4
# (DHT — define Huffman table), SOF8 (reserved), SOF12 (reserved).
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _jpeg(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    pos = 2
    n = len(data)
    while pos < n - 1:
        # Walk segment markers. A marker is 0xFF followed by a non-zero
        # byte; consecutive 0xFF fills are legal and skipped here.
        if data[pos] != 0xFF:
            return None
        while pos < n and data[pos] == 0xFF:
            pos += 1
        if pos >= n:
            return None
        marker = data[pos]
        pos += 1
        # Standalone markers (no segment length): SOI, EOI, RSTn, TEM.
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if pos + 2 > n:
            return None
        seg_len = struct.unpack(">H", data[pos : pos + 2])[0]
        if seg_len < 2 or pos + seg_len > n:
            return None
        if marker in _JPEG_SOF_MARKERS:
            # Segment body: [precision:1][height:2][width:2][components:1]
            if seg_len < 7:
                return None
            h, w = struct.unpack(">HH", data[pos + 3 : pos + 7])
            return (w, h) if (w > 0 and h > 0) else None
        pos += seg_len
    return None


# ---- GIF --------------------------------------------------------------


def _gif(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w, h = struct.unpack("<HH", data[6:10])
    return (w, h) if (w > 0 and h > 0) else None


# ---- WebP -------------------------------------------------------------


def _webp(data: bytes) -> tuple[int, int] | None:
    # RIFF header: "RIFF" + 4-byte size + "WEBP" then a chunk:
    # VP8  (lossy), VP8L (lossless), or VP8X (extended).
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        # 10 bytes chunk header, then VP8 frame: 3-byte tag, 3-byte
        # start code (0x9d 0x01 0x2a), then 14-bit width/height each
        # (the upper 2 bits are the scale, ignored here).
        if len(data) < 30:
            return None
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return (w, h) if (w > 0 and h > 0) else None
    if chunk == b"VP8L":
        # Header byte 0x2f, then a 32-bit little-endian payload where:
        # bits 0..13   → width - 1
        # bits 14..27  → height - 1
        if len(data) < 25 or data[20] != 0x2F:
            return None
        b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
        w = 1 + (((b1 & 0x3F) << 8) | b0)
        h = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return (w, h)
    if chunk == b"VP8X":
        # VP8X chunk: 4 reserved+flag bytes, then 3-byte (W-1) +
        # 3-byte (H-1), little-endian 24-bit values.
        if len(data) < 30:
            return None
        wm1 = data[24] | (data[25] << 8) | (data[26] << 16)
        hm1 = data[27] | (data[28] << 8) | (data[29] << 16)
        return (wm1 + 1, hm1 + 1)
    return None
