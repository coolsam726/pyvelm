"""HTML sanitizer for ``Html`` field values and ``mail.template`` bodies.

The framework stores HTML written by admins (email templates, rich text in
chatter etc.). That HTML lands in the DOM via ``x-html`` and in outgoing
SMTP messages, so anything that would execute code in either context has
to be stripped before storage. We deliberately do this at the **write**
boundary (in the field's ``to_python`` / ``to_sql_param``) so a malicious
payload never reaches the database — even a future bug that bypasses the
``x-html`` render path can't reach back to a tainted column.

The allowlist is small and email-shaped: structural tags, common inline
formatting, lists, tables, links, images. Everything else is silently
dropped (tag stripped; children kept). No external dependency — the
parser is pure ``html.parser``. For complex Markdown-flavoured content,
swap this for ``bleach`` or ``nh3`` at the field level; the public API
is one function (:func:`sanitize_html`).
"""
from __future__ import annotations

import re
from html import escape as _escape
from html.parser import HTMLParser

# Tags that are allowed through verbatim. Anything not in this set has its
# tag stripped but its inner text/children are kept (so a stray ``<script>``
# becomes nothing; a stray ``<font>`` becomes its text).
_ALLOWED_TAGS: frozenset[str] = frozenset({
    "a", "abbr", "b", "blockquote", "br", "caption",
    "code", "div", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "input", "label", "li", "mark", "ol",
    "p", "pre", "s", "small", "span", "strike", "strong",
    "sub", "sup", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "u", "ul",
})

# Tags whose **contents** must also be discarded (script bodies, style
# blocks etc.). The HTMLParser still yields end-tag events, so we just
# track depth via a counter set when we see one of these.
_DROP_TAGS: frozenset[str] = frozenset({"script", "style", "iframe", "object", "embed"})

# Attributes allowed on every tag (e.g. ``class``, ``title``).
_COMMON_ATTRS: frozenset[str] = frozenset({
    "class", "title", "id", "lang", "dir", "style",
})

# Per-tag attribute allowlists. Merged with _COMMON_ATTRS at check time.
_TAG_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "target", "rel", "name"}),
    "img": frozenset({"src", "alt", "width", "height"}),
    "td": frozenset({"colspan", "rowspan", "align", "valign"}),
    "th": frozenset({"colspan", "rowspan", "align", "valign", "scope"}),
    "table": frozenset({"border", "cellpadding", "cellspacing", "width"}),
    "ol": frozenset({"start", "type", "reversed"}),
    "li": frozenset({"value"}),
    # TipTap TaskList emits <input type="checkbox" checked> inside <li>.
    # Email clients usually strip <input>, but we keep it for the editor's
    # own round-trip; non-checkbox/radio types are dropped below.
    "input": frozenset({"type", "checked", "disabled"}),
    "label": frozenset(),
}

# Tags whose ``type`` attribute must match an allowlist or the tag is
# dropped wholesale. Used for ``<input>`` so we never accept
# ``<input type="text">``-shaped payloads in user-authored HTML.
_TAG_TYPE_ALLOWLIST: dict[str, frozenset[str]] = {
    "input": frozenset({"checkbox", "radio"}),
}

# URL schemes allowed on href/src. Anything else (notably ``javascript:``
# and ``data:`` for non-image content) is dropped on the floor — the
# attribute is removed and the rest of the tag survives.
_SAFE_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto", "tel"})
_SAFE_IMG_SCHEMES: frozenset[str] = frozenset({"http", "https", "data", "cid"})

# Reject CSS declarations whose value points back at JS via url() or
# expression(). Cheap regex; not a full CSS parser — anything risky is
# stripped wholesale, the surviving declarations are property:value pairs
# with no `expression()` / `url(javascript:...)` content.
_CSS_BANNED = re.compile(r"(expression|javascript|behaviou?r|@import)", re.IGNORECASE)


def _scheme_of(url: str) -> str:
    if not url:
        return ""
    m = re.match(r"\s*([a-zA-Z][a-zA-Z0-9+.\-]*):", url)
    return m.group(1).lower() if m else ""


def _safe_url(value: str, *, image: bool = False) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    scheme = _scheme_of(v)
    allowed = _SAFE_IMG_SCHEMES if image else _SAFE_SCHEMES
    if scheme and scheme not in allowed:
        return None
    return v


def _safe_style(value: str) -> str | None:
    if not value:
        return None
    if _CSS_BANNED.search(value):
        return None
    # Keep ``property: value; property: value`` shape. Drop declarations
    # whose value embeds a banned token (caught above) or unbalanced
    # parentheses. Anything left is rendered as-is.
    parts = []
    for decl in value.split(";"):
        if not decl.strip():
            continue
        if "(" in decl and not decl.count("(") == decl.count(")"):
            continue
        parts.append(decl.strip())
    return "; ".join(parts) if parts else None


class _SanitizingParser(HTMLParser):
    """Walks the input HTML and emits a sanitized rebuild."""

    def __init__(self) -> None:
        # convert_charrefs=False so we keep numeric / named entities verbatim
        # (passing them through ``_escape`` would double-encode).
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        # Depth counter for "drop tag + contents" elements. Non-zero means
        # we're inside a <script> / <style> and should ignore everything
        # until the matching end tag.
        self._drop_depth = 0

    # ---- helpers ----

    def _attrs_for(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed = _COMMON_ATTRS | _TAG_ATTRS.get(tag, frozenset())
        type_allowlist = _TAG_TYPE_ALLOWLIST.get(tag)
        out: list[str] = []
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            if name.startswith("on"):  # event handlers
                continue
            # ``data-*`` attributes are inert by spec and used by TipTap to
            # carry round-trip state (taskList items, etc.). Allow them on
            # any tag, with the same value-escaping as everything else.
            is_data = name.startswith("data-")
            if not is_data and name not in allowed:
                continue
            value = "" if raw_value is None else raw_value
            if name == "href":
                cleaned = _safe_url(value, image=False)
            elif name == "src":
                cleaned = _safe_url(value, image=True)
            elif name == "style":
                cleaned = _safe_style(value)
            elif name == "type" and type_allowlist is not None:
                cleaned = value if value.lower() in type_allowlist else None
            else:
                cleaned = value
            if cleaned is None:
                continue
            out.append(f'{name}="{_escape(cleaned, quote=True)}"')
        return (" " + " ".join(out)) if out else ""

    def _should_drop_tag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> bool:
        """A few tags must be dropped entirely (not just their attrs) when
        a guarded attribute fails validation. ``<input type="text">`` is
        the canonical case — keeping the tag with the type stripped would
        still produce an editable text field, so we throw away the whole
        element."""
        guard = _TAG_TYPE_ALLOWLIST.get(tag)
        if guard is None:
            return False
        type_val = next(
            (v for n, v in attrs if (n or "").lower() == "type" and v),
            None,
        )
        return type_val is None or type_val.lower() not in guard

    # ---- HTMLParser callbacks ----

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if tag not in _ALLOWED_TAGS:
            return
        if self._should_drop_tag(tag, attrs):
            return
        self.out.append(f"<{tag}{self._attrs_for(tag, attrs)}>")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS or self._drop_depth:
            return
        if tag not in _ALLOWED_TAGS:
            return
        if self._should_drop_tag(tag, attrs):
            return
        self.out.append(f"<{tag}{self._attrs_for(tag, attrs)} />")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS:
            if self._drop_depth:
                self._drop_depth -= 1
            return
        if self._drop_depth:
            return
        if tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        self.out.append(_escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if self._drop_depth:
            return
        self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._drop_depth:
            return
        self.out.append(f"&#{name};")

    # Discard comments + processing instructions. They can carry conditional
    # IE-era ``<!--[if IE]><script>…</script><![endif]-->`` attacks.
    def handle_comment(self, data: str) -> None:  # noqa: D401 - HTMLParser API
        return

    def handle_pi(self, data: str) -> None:  # noqa: D401 - HTMLParser API
        return

    def handle_decl(self, decl: str) -> None:  # noqa: D401 - HTMLParser API
        return


def sanitize_html(value: str | None) -> str:
    """Return *value* with disallowed tags / attributes / URL schemes stripped.

    ``None`` / ``""`` round-trip unchanged. The output is **always** a
    `str`; callers that want :class:`markupsafe.Markup` can wrap it.
    """
    if not value:
        return "" if value is not None else ""
    p = _SanitizingParser()
    p.feed(str(value))
    p.close()
    return "".join(p.out)
