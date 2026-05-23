"""Display formatting for report column values."""
from __future__ import annotations

from typing import Any

_VALID_FORMAT_TYPES = frozenset({"text", "number", "integer", "currency"})
_VALID_ALIGNS = frozenset({"left", "center", "right"})
_VALID_CURRENCY_SOURCES = frozenset({"field", "fixed"})


def normalize_column_format(raw: Any) -> dict[str, Any]:
    """Return a normalized format dict from a column definition fragment."""
    if not raw or not isinstance(raw, dict):
        return {"type": "text", "align": "left"}
    ftype = raw.get("type") or "text"
    if ftype not in _VALID_FORMAT_TYPES:
        ftype = "text"
    align = raw.get("align") or "left"
    if align not in _VALID_ALIGNS:
        align = "left"
    out: dict[str, Any] = {"type": ftype, "align": align}
    decimals = raw.get("decimals")
    if decimals is not None:
        try:
            out["decimals"] = max(0, min(8, int(decimals)))
        except (TypeError, ValueError):
            pass
    if ftype == "currency":
        src = raw.get("currency_source", "field")
        if src not in _VALID_CURRENCY_SOURCES:
            src = "field"
        out["currency_source"] = src
        if src == "fixed" and raw.get("currency_id") is not None:
            try:
                out["currency_id"] = int(raw["currency_id"])
            except (TypeError, ValueError):
                pass
        elif src == "field":
            cf = raw.get("currency_field")
            out["currency_field"] = cf if isinstance(cf, str) and cf else "currency_id"
        symbol = raw.get("symbol")
        if symbol is not None and isinstance(symbol, str) and symbol.strip():
            out["symbol"] = symbol.strip()
    return out


def format_display_value(
    value: Any,
    *,
    fmt: dict[str, Any] | None,
    label_value: Any = None,
    currency_symbol: str | None = None,
) -> str:
    """Format a cell for preview/export display."""
    if label_value is not None:
        return str(label_value)
    if value is None:
        return ""
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    fmt = normalize_column_format(fmt)
    ftype = fmt["type"]
    if ftype == "integer":
        try:
            return f"{round(float(value)):,}"
        except (TypeError, ValueError):
            return str(value)
    if ftype in ("number", "currency"):
        decimals = fmt.get("decimals", 2 if ftype == "currency" else 2)
        try:
            num = float(value)
        except (TypeError, ValueError):
            return str(value)
        text = f"{num:,.{decimals}f}"
        if ftype == "currency":
            sym = currency_symbol if currency_symbol is not None else fmt.get("symbol") or ""
            return f"{sym}{text}" if sym else text
        return text
    return str(value)
