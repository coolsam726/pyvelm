"""Unit tests for the stdlib image-dimension parser.

Fixtures are constructed in-code from spec-minimum byte sequences so
the test file stays self-contained (no binary blobs to manage).
"""

import struct
import unittest

from pyvelm.image_meta import read_image_dimensions


def _make_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    length = struct.pack(">I", 13)
    ihdr = b"IHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    # Trailing 4-byte CRC placeholder — the parser doesn't validate it.
    return sig + length + ihdr + b"\x00\x00\x00\x00"


def _make_jpeg(width: int, height: int) -> bytes:
    # SOI + APP0 (JFIF) + SOF0 with our dimensions + EOI.
    soi = b"\xff\xd8"
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof0_body = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sof0 = b"\xff\xc0" + struct.pack(">H", 2 + len(sof0_body)) + sof0_body
    eoi = b"\xff\xd9"
    return soi + app0 + sof0 + eoi


def _make_gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00"


def _make_webp_vp8x(width: int, height: int) -> bytes:
    # VP8X carries (W-1) / (H-1) as 24-bit LE values; minimum-shape
    # extended chunk lets us round-trip arbitrary dimensions.
    wm1, hm1 = width - 1, height - 1
    vp8x_body = (
        b"\x00\x00\x00\x00"
        + bytes([wm1 & 0xFF, (wm1 >> 8) & 0xFF, (wm1 >> 16) & 0xFF])
        + bytes([hm1 & 0xFF, (hm1 >> 8) & 0xFF, (hm1 >> 16) & 0xFF])
    )
    chunk = b"VP8X" + struct.pack("<I", len(vp8x_body)) + vp8x_body
    riff = b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
    return riff


class ImageMetaTests(unittest.TestCase):
    def test_png(self):
        self.assertEqual(read_image_dimensions(_make_png(640, 480), "image/png"), (640, 480))

    def test_jpeg(self):
        self.assertEqual(read_image_dimensions(_make_jpeg(800, 600), "image/jpeg"), (800, 600))

    def test_jpeg_pjpeg_mime_alias(self):
        self.assertEqual(read_image_dimensions(_make_jpeg(120, 90), "image/pjpeg"), (120, 90))

    def test_gif(self):
        self.assertEqual(read_image_dimensions(_make_gif(50, 100), "image/gif"), (50, 100))

    def test_webp_vp8x(self):
        self.assertEqual(read_image_dimensions(_make_webp_vp8x(2048, 1536), "image/webp"), (2048, 1536))

    def test_mimetype_with_charset_suffix(self):
        self.assertEqual(
            read_image_dimensions(_make_png(4, 4), "image/png; charset=binary"),
            (4, 4),
        )

    def test_unknown_mime_returns_none(self):
        self.assertIsNone(read_image_dimensions(_make_png(1, 1), "image/tiff"))
        self.assertIsNone(read_image_dimensions(_make_png(1, 1), "application/pdf"))

    def test_truncated_png_returns_none(self):
        self.assertIsNone(read_image_dimensions(_make_png(100, 100)[:12], "image/png"))

    def test_signature_mismatch_returns_none(self):
        self.assertIsNone(read_image_dimensions(b"NOTAPNG\x00" * 10, "image/png"))

    def test_empty_bytes_returns_none(self):
        self.assertIsNone(read_image_dimensions(b"", "image/png"))


if __name__ == "__main__":
    unittest.main()
