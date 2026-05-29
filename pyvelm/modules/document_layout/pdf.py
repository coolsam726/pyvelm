"""HTML → PDF via the wkhtmltopdf binary.

Isolated here so the engine is swappable. Renders HTML from stdin to PDF on
stdout (no temp files). Raises a clear error if the binary isn't installed.
"""
from __future__ import annotations

import shutil
import subprocess

_INSTALL_HINT = (
    "wkhtmltopdf is required for PDF rendering. Install it (e.g. "
    "`apt-get install -y wkhtmltopdf`) and ensure it's on PATH."
)


def is_available() -> bool:
    return shutil.which("wkhtmltopdf") is not None


def html_to_pdf(
    html: str,
    *,
    paper: str = "A4",
    landscape: bool = False,
    footer: bool = True,
) -> bytes:
    """Render *html* to PDF bytes with wkhtmltopdf."""
    exe = shutil.which("wkhtmltopdf")
    if not exe:
        raise RuntimeError(_INSTALL_HINT)
    cmd = [
        exe, "--quiet", "--encoding", "utf-8",
        "--enable-local-file-access",
        "--page-size", paper,
        "--margin-top", "16", "--margin-bottom", "16",
        "--margin-left", "12", "--margin-right", "12",
    ]
    if landscape:
        cmd += ["--orientation", "Landscape"]
    if footer:
        cmd += ["--footer-center", "[page] / [topage]", "--footer-font-size", "8",
                "--footer-spacing", "4"]
    cmd += ["-", "-"]  # HTML on stdin, PDF on stdout
    proc = subprocess.run(
        cmd, input=html.encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    # wkhtmltopdf can emit warnings on stderr yet still produce a valid PDF;
    # only treat it as a failure when there's no PDF output.
    if not proc.stdout.startswith(b"%PDF"):
        err = proc.stderr.decode("utf-8", "replace")[:500]
        raise RuntimeError(f"wkhtmltopdf failed (rc={proc.returncode}): {err}")
    return proc.stdout
