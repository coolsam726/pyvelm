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

    def test_png_bad_ihdr(self):
        bad = bytearray(_make_png(10, 10))
        bad[12:16] = b"XXXX"
        self.assertIsNone(read_image_dimensions(bytes(bad), "image/png"))

    def test_png_zero_dimensions(self):
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = b"IHDR" + struct.pack(">II", 0, 10) + b"\x08\x02\x00\x00\x00"
        data = sig + struct.pack(">I", 13) + ihdr + b"\x00\x00\x00\x00"
        self.assertIsNone(read_image_dimensions(data, "image/png"))

    def test_jpeg_invalid_marker(self):
        self.assertIsNone(read_image_dimensions(b"\xff\xd8\xff\xee", "image/jpeg"))

    def test_webp_vp8_chunk(self):
        # Minimal VP8 lossy chunk with start code and dimensions.
        vp8 = (
            b"RIFF"
            + struct.pack("<I", 20)
            + b"WEBP"
            + b"VP8 "
            + struct.pack("<I", 10)
            + b"\x00\x00\x00"
            + b"\x9d\x01\x2a"
            + struct.pack("<HH", 64, 48)
        )
        self.assertEqual(read_image_dimensions(vp8, "image/webp"), (64, 48))

    def test_webp_vp8l_chunk(self):
        # VP8L: signature byte 0x2f + packed 32-bit size field (needs len >= 30).
        payload = bytes([0x2F, 0x3F, 0x00, 0x00, 0x00]) + b"\x00" * 5
        chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
        riff = b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
        dims = read_image_dimensions(riff, "image/webp")
        self.assertIsNotNone(dims)
        self.assertGreater(dims[0], 0)
        self.assertGreater(dims[1], 0)

    def test_webp_unknown_chunk(self):
        riff = b"RIFF" + struct.pack("<I", 4) + b"WEBP" + b"XXXX" + struct.pack("<I", 0)
        self.assertIsNone(read_image_dimensions(riff, "image/webp"))

    def test_parse_exception_returns_none(self):
        with unittest.mock.patch(
            "pyvelm.image_meta._png", side_effect=RuntimeError("boom")
        ):
            self.assertIsNone(read_image_dimensions(_make_png(1, 1), "image/png"))

    def test_gif_zero_dimensions(self):
        data = b"GIF89a" + struct.pack("<HH", 0, 10) + b"\x00"
        self.assertIsNone(read_image_dimensions(data, "image/gif"))

    def test_jpeg_no_sof_marker(self):
        # SOI + APP0 only, no SOF — parser walks to end.
        data = _make_jpeg(10, 10)[:30]
        self.assertIsNone(read_image_dimensions(data, "image/jpeg"))

    def test_webp_vp8_bad_start_code(self):
        riff = (
            b"RIFF"
            + struct.pack("<I", 20)
            + b"WEBP"
            + b"VP8 "
            + struct.pack("<I", 10)
            + b"\x00\x00\x00"
            + b"\x00\x00\x00"
            + struct.pack("<HH", 64, 48)
        )
        self.assertIsNone(read_image_dimensions(riff, "image/webp"))

    def test_webp_vp8x_truncated(self):
        self.assertIsNone(read_image_dimensions(_make_webp_vp8x(10, 10)[:20], "image/webp"))

    def test_webp_vp8l_bad_signature(self):
        payload = bytes([0x00, 0x3F, 0x00, 0x00, 0x00]) + b"\x00" * 5
        chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
        riff = b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
        self.assertIsNone(read_image_dimensions(riff, "image/webp"))

    def test_jpeg_truncated_segment(self):
        data = b"\xff\xd8\xff\xc0" + b"\x00\x01"
        self.assertIsNone(read_image_dimensions(data, "image/jpeg"))

    def test_jpeg_invalid_non_ff_byte(self):
        data = b"\xff\xd8\x00\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", 10, 10) + b"\x03"
        self.assertIsNone(read_image_dimensions(data, "image/jpeg"))

    def test_jpeg_sof_zero_height(self):
        body = struct.pack(">BHHB", 8, 0, 10, 1) + b"\x01"
        sof0 = b"\xff\xc0" + struct.pack(">H", 2 + len(body)) + body
        self.assertIsNone(read_image_dimensions(b"\xff\xd8" + sof0, "image/jpeg"))

    def test_jpeg_too_short_header(self):
        self.assertIsNone(read_image_dimensions(b"\xff\xd8", "image/jpeg"))

    def test_jpeg_marker_past_eof(self):
        data = b"\xff\xd8\xff"
        self.assertIsNone(read_image_dimensions(data, "image/jpeg"))

    def test_jpeg_sof_segment_too_short(self):
        sof0 = b"\xff\xc0" + struct.pack(">H", 6) + b"\x08\x00\x0a\x00"
        self.assertIsNone(read_image_dimensions(b"\xff\xd8" + sof0, "image/jpeg"))

    def test_jpeg_no_frame_before_eof(self):
        app0 = b"\xff\xe0" + struct.pack(">H", 2)
        self.assertIsNone(read_image_dimensions(b"\xff\xd8" + app0, "image/jpeg"))

    def test_gif_bad_magic(self):
        self.assertIsNone(read_image_dimensions(b"GIF00a" + struct.pack("<HH", 1, 1), "image/gif"))

    def test_webp_vp8_chunk_too_short(self):
        riff = b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8 " + struct.pack("<I", 0)
        self.assertIsNone(read_image_dimensions(riff, "image/webp"))

    def test_webp_vp8x_chunk_too_short(self):
        riff = b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8X" + struct.pack("<I", 0)
        self.assertIsNone(read_image_dimensions(riff, "image/webp"))

    def test_jpeg_rst_then_sof(self):
        sof_body = struct.pack(">BHHB", 8, 12, 34, 1) + b"\x01"
        sof0 = b"\xff\xc0" + struct.pack(">H", 2 + len(sof_body)) + sof_body
        data = b"\xff\xd8\xff\xd0" + sof0
        self.assertEqual(read_image_dimensions(data, "image/jpeg"), (34, 12))

    def test_jpeg_eof_at_marker(self):
        self.assertIsNone(read_image_dimensions(b"\xff\xd8\xff", "image/jpeg"))

    def test_webp_too_short(self):
        self.assertIsNone(read_image_dimensions(b"RIFF\x00\x00WEBP", "image/webp"))


if __name__ == "__main__":
    unittest.main()
