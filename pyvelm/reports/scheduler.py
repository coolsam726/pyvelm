"""Scheduled report execution via ir.cron + ir.actions.server."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta

from .export_xlsx import export_csv, export_xlsx
from .export_pdf import export_pdf
from .service import execute_report, log_run


def run_scheduled_report(env, report_rec, *, output_format: str | None = None) -> dict:
    """Execute a report and store the output as an ir.attachment."""
    fmt = output_format or getattr(report_rec, "output_format", None) or "xlsx"
    result = execute_report(env, report_rec, params={})
    title = report_rec.name or "Report"

    if fmt == "xlsx":
        data = export_xlsx(result, title=title)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif fmt == "csv":
        data = export_csv(result).encode("utf-8")
        mimetype = "text/csv"
        ext = "csv"
    elif fmt == "pdf":
        data = export_pdf(result, title=title)
        mimetype = "application/pdf"
        ext = "pdf"
    else:
        raise ValueError(f"Unknown output format {fmt!r}")

    Attachment = env["ir.attachment"]
    att = Attachment.create({
        "name": f"{title}.{ext}",
        "datas_fname": f"{title}.{ext}",
        "mimetype": mimetype,
        "datas": base64.b64encode(data).decode("ascii"),
        "file_size": len(data),
        "res_model": "ir.report",
        "res_id": report_rec.id,
        "type": "binary",
    })
    log_run(
        env, report_rec,
        row_count=result.row_count,
        duration_ms=result.duration_ms,
        fmt=f"scheduled_{fmt}",
    )
    return {"attachment_id": att.id, "row_count": result.row_count, "format": fmt}


def ensure_daily_cron(env, report_rec) -> None:
    """Create or refresh a daily cron job for *report_rec*."""
    if "ir.cron" not in env.registry or "ir.actions.server" not in env.registry:
        return
    Action = env["ir.actions.server"]
    Cron = env["ir.cron"]
    code = f"""
report = env['ir.report'].browse([{report_rec.id}])
from pyvelm.reports.scheduler import run_scheduled_report
run_scheduled_report(env, report)
"""
    action = None
    if report_rec.cron_id:
        action = report_rec.cron_id.action_id
    if not action:
        action = Action.create({
            "name": f"Report: {report_rec.name}",
            "model": "ir.report",
            "action_type": "code",
            "code": code,
        })
    else:
        action.write({"code": code, "name": f"Report: {report_rec.name}"})

    if report_rec.cron_id:
        report_rec.cron_id.write({
            "name": f"Report: {report_rec.name}",
            "active": True,
            "action_id": action,
        })
        return

    cron = Cron.create({
        "name": f"Report: {report_rec.name}",
        "action_id": action,
        "interval_number": 1,
        "interval_type": "days",
        "nextcall": datetime.utcnow() + timedelta(minutes=1),
        "active": True,
    })
    report_rec.write({"cron_id": cron})


def disable_schedule(env, report_rec) -> None:
    if report_rec.cron_id:
        report_rec.cron_id.write({"active": False})
