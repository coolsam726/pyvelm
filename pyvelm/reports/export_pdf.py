"""PDF export for report results (fpdf2 — pure Python)."""
from __future__ import annotations

import io
from typing import Any

from .execute import ReportResult
from .format import format_display_value


def export_pdf(result: ReportResult, *, title: str = "Report") -> bytes:
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise RuntimeError(
            "fpdf2 is required for PDF export (pip install fpdf2)"
        ) from e

    pdf = FPDF(orientation="L" if len(result.columns) > 6 else "P")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, (title or "Report")[:120], ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"{result.row_count} rows", ln=True)
    pdf.ln(4)

    col_count = max(len(result.columns), 1)
    page_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = page_w / col_count

    _ALIGN = {"left": "L", "center": "C", "right": "R"}

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(240, 240, 240)
    for col in result.columns:
        align = _ALIGN.get(col.format_dict().get("align", "left"), "L")
        pdf.cell(col_w, 7, col.label[:40], border=1, fill=True, align=align)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for row in result.rows:
        for col in result.columns:
            label_key = f"{col.key}__label"
            label_val = row.get(label_key)
            text = format_display_value(
                row.get(col.key),
                fmt=col.format_dict(),
                label_value=label_val,
                currency_symbol=row.get(f"{col.key}__currency_symbol"),
            )
            align = _ALIGN.get(col.format_dict().get("align", "left"), "L")
            pdf.cell(col_w, 6, text[:60], border=1, align=align)
        pdf.ln()

    return bytes(pdf.output())
