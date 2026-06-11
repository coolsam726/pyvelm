"""View-action lookup and inline form rendering for toolbar dialogs."""
from __future__ import annotations

import json
import re
from .fields import Boolean, Char, Integer, Many2one, Text
from .views import resolve_arch


def view_action_key(label: str) -> str:
    """Slug from an action label (``Quick add`` → ``quick-add``)."""
    normalized = label.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized)
    return slug.strip("-")


def view_action_form_url(
    module: str,
    view_name: str,
    slot: str,
    action_key: str,
    record_id: int | str = 0,
) -> str:
    base = (
        f"/web/view-actions/{module}/{view_name}/{slot}/{action_key}/form"
    )
    rid = int(record_id or 0)
    return f"{base}?record={rid}" if rid > 0 else base


class ViewActionLocator:
    """Find a declared page/header action by slug."""

    def find(
        self,
        env,
        module: str,
        view_name: str,
        slot: str,
        action_key: str,
    ) -> dict | None:
        from .render import _load_ui_view

        view = _load_ui_view(env, module, view_name)
        if view is None:
            return None
        arch = resolve_arch(view)
        if slot in ("page", "page_actions"):
            actions = arch.get("page_actions") or []
        elif slot in ("header", "header_actions"):
            actions = arch.get("header_actions") or []
        else:
            return None
        for action in actions:
            if not isinstance(action, dict):
                continue
            label = str(action.get("label") or "")
            if label and view_action_key(label) == action_key:
                return action
        return None


def _humanize_field_name(name: str) -> str:
    return name.replace("_", " ").strip().title()


def inline_action_form_fields(
    env,
    model: str,
    form_arch: dict,
    values: dict | None = None,
) -> list[dict]:
    """Materialize inline form fields for the action dialog template."""
    values = values or {}
    model_cls = env.registry[model]
    fields_out: list[dict] = []

    for section in form_arch.get("sections") or []:
        if not isinstance(section, dict):
            continue
        pages = section.get("pages")
        if pages is not None:
            for page in pages:
                if not isinstance(page, dict):
                    continue
                for spec in page.get("fields") or []:
                    field = _inline_field_spec(env, model, model_cls, spec, values)
                    if field is not None:
                        fields_out.append(field)
            continue
        for spec in section.get("fields") or []:
            field = _inline_field_spec(env, model, model_cls, spec, values)
            if field is not None:
                fields_out.append(field)
    return fields_out


def _inline_field_spec(env, model, model_cls, field_spec, values: dict) -> dict | None:
    if isinstance(field_spec, str):
        field_spec = {"name": field_spec}
    if not isinstance(field_spec, dict) or not field_spec.get("name"):
        return None
    name = str(field_spec["name"])
    velm_field = model_cls._fields.get(name)
    label = field_spec.get("label") or (
        getattr(velm_field, "string", None) if velm_field else None
    ) or _humanize_field_name(name)
    required = bool(getattr(velm_field, "required", False)) if velm_field else False
    value = values.get(name)
    widget = field_spec.get("widget")

    if isinstance(velm_field, Boolean) or widget == "toggle":
        return {
            "name": name,
            "label": label,
            "type": "boolean",
            "required": required,
            "value": bool(value),
        }

    if isinstance(velm_field, Many2one):
        Model = env[velm_field.comodel_name]
        rows = Model.search([], limit=200, order='"id" ASC')
        options = []
        for rec in rows:
            dn = getattr(rec, "display_name", None)
            options.append(
                {
                    "id": rec.id,
                    "label": str(dn) if dn else str(rec.id),
                }
            )
        return {
            "name": name,
            "label": label,
            "type": "many2one",
            "required": required,
            "value": value,
            "options": options,
        }

    if isinstance(velm_field, Text) or widget == "text":
        return {
            "name": name,
            "label": label,
            "type": "text",
            "required": required,
            "value": value,
            "multiline": True,
        }

    if isinstance(velm_field, Integer):
        return {
            "name": name,
            "label": label,
            "type": "integer",
            "required": required,
            "value": value,
        }

    if isinstance(velm_field, Char) or velm_field is None:
        return {
            "name": name,
            "label": label,
            "type": "char",
            "required": required,
            "value": value,
        }

    return {
        "name": name,
        "label": label,
        "type": "char",
        "required": required,
        "value": value if value is None or isinstance(value, (str, int, float)) else json.dumps(value),
    }


def render_view_action_inline_form(
    *,
    title: str,
    fields: list[dict],
    submit_url: str,
    record_id: int = 0,
) -> str:
    from .render import _env

    template = _env.get_template("view_action_inline_form.html")
    return template.render(
        title=title,
        fields=fields,
        submit_url=submit_url,
        record_id=record_id,
    )
