"""Unit coverage for ``document_layout`` (hooks, pdf, web, layout gaps).

Bundled module code lives under ``pyvelm/modules/document_layout/`` and is
imported as top-level ``document_layout`` (same as the loader). These tests
complement ``test_document_layout_all.py`` (layout rendering) and keep CI
coverage above the project gate when the module ships in the wheel.
"""
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_MODULE_ROOT = Path(__file__).resolve().parent.parent / "modules"
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))

import document_layout  # noqa: E402  — package __init__ (widgets)
import document_layout.api as dl_api  # noqa: E402
import document_layout.hooks as dl_hooks  # noqa: E402
import document_layout.layout as dl_layout  # noqa: E402
import document_layout.pdf as dl_pdf  # noqa: E402
import document_layout.web as dl_web  # noqa: E402
from document_layout.widgets import _render_design_button  # noqa: E402


def _reset_registry() -> None:
    dl_layout._REGISTRY.clear()


class TemplateDirTests(unittest.TestCase):
    def test_resolve_template_dir_finds_external_layout(self):
        d = dl_layout._resolve_template_dir()
        self.assertTrue((d / "external_layout.html").is_file())

    def test_resolve_template_dir_import_error_branch(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "pyvelm":
                raise ImportError("no pyvelm")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            d = dl_layout._resolve_template_dir()
        self.assertTrue((d / "external_layout.html").is_file())


class RegistryRenderTests(unittest.TestCase):
    def setUp(self):
        _reset_registry()

    def test_api_reexports_match_layout(self):
        self.assertIs(dl_api.register_document, dl_layout.register_document)
        self.assertIs(dl_api.render_pdf, dl_layout.render_pdf)

    def test_register_and_render_html(self):
        dl_layout.register_document(
            "inv",
            model="sale.order",
            render_body=lambda env, rec: f"<p>{rec.name}</p>",
            title="Invoice",
        )
        self.assertEqual(dl_layout.document_spec("inv")["title"], "Invoice")

        record = SimpleNamespace(name="SO001")
        Model = MagicMock()
        Model.search.return_value = record
        Model.browse.return_value = record
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=Model)
        env.registry = {}
        env.company_id = None
        env.__getitem__.side_effect = lambda m: (
            Model if m == "sale.order" else MagicMock(search=lambda *a, **k: None)
        )

        with patch.object(dl_layout, "_company_context", return_value=_sample_company_ctx()):
            html = dl_layout.render_html(env, "inv", 42, preview=True)
        self.assertIn("SO001", html)
        self.assertIn("doc-frame", html)

    def test_render_html_unknown_key(self):
        with self.assertRaises(KeyError):
            dl_layout.render_html(MagicMock(), "missing", 1)

    def test_render_html_missing_record(self):
        dl_layout.register_document("x", model="m", render_body=lambda e, r: "")
        Model = MagicMock()
        Model.search.return_value = None
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=Model)
        with self.assertRaises(ValueError):
            dl_layout.render_html(env, "x", 99)

    @patch.object(dl_layout._pdf, "html_to_pdf", return_value=b"%PDF-fake")
    def test_render_pdf(self, mock_pdf):
        dl_layout.register_document("inv", model="m", render_body=lambda e, r: "body")
        Model = MagicMock()
        Model.search.return_value = SimpleNamespace()
        Model.browse.return_value = SimpleNamespace()
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=Model)
        with patch.object(dl_layout, "_company_context", return_value={"paper": "A4"}):
            with patch.object(dl_layout, "render_html", return_value="<html></html>"):
                data, paper = dl_layout.render_pdf(env, "inv", 1)
        self.assertEqual(data, b"%PDF-fake")
        self.assertEqual(paper, "A4")
        mock_pdf.assert_called_once()


def _sample_company_ctx(**extra):
    base = {
        "name": "Acme",
        "address_lines": [],
        "logo_url": "",
        "accent": "#111",
        "secondary": "#111",
        "font": "",
        "font_face_css": "",
        "copyright": "",
        "layout": "light",
        "paper": "A4",
        "paper_width": "210mm",
        "paper_height": "297mm",
        "paper_content_min": "265mm",
        "folder_tint": "#eee",
        "vat": "",
    }
    base.update(extra)
    return base


class CompanyContextTests(unittest.TestCase):
    def test_empty_registry_defaults(self):
        env = MagicMock()
        env.company_id = None
        Company = MagicMock()
        Company.search.return_value = None
        env.__getitem__ = MagicMock(return_value=Company)
        ctx = dl_layout._company_context(env)
        self.assertEqual(ctx["layout"], "light")
        self.assertEqual(ctx["paper"], "A4")

    def test_company_id_lookup(self):
        env = MagicMock()
        env.company_id = 7
        company = SimpleNamespace(
            name="Co",
            primary_color="#abc",
            secondary_color="",
            google_font="",
            paper_format="Letter",
            logo_url="",
            copyright_text="",
            document_layout="bold",
            vat="",
            _address_lines=lambda: ["line"],
        )
        Company = MagicMock()
        Company.search.return_value = company
        env.__getitem__ = MagicMock(return_value=Company)
        ctx = dl_layout._company_context(env)
        self.assertEqual(ctx["layout"], "bold")
        self.assertEqual(ctx["paper_width"], "215.9mm")


class LogoAndFontTests(unittest.TestCase):
    def test_logo_empty_and_data_uri_passthrough(self):
        env = MagicMock()
        self.assertEqual(dl_layout._logo_data_uri(env, ""), "")
        self.assertEqual(dl_layout._logo_data_uri(env, "data:x"), "data:x")

    def test_logo_attachment_inline(self):
        att = SimpleNamespace(type="binary", url="", mimetype="image/png", fetch_content=lambda: b"png")
        Attachment = MagicMock()
        Attachment.search.return_value = att
        env = MagicMock()
        env.registry = {"ir.attachment": Attachment}
        env.sudo.return_value = env
        env.__getitem__ = MagicMock(return_value=Attachment)
        out = dl_layout._logo_data_uri(env, "/api/attachment/9/download")
        self.assertTrue(out.startswith("data:image/png;base64,"))

    def test_logo_attachment_url_type(self):
        att = SimpleNamespace(type="url", url="https://cdn/logo.png")
        Attachment = MagicMock()
        Attachment.search.return_value = att
        env = MagicMock()
        env.registry = {"ir.attachment": Attachment}
        env.sudo.return_value = env
        env.__getitem__ = MagicMock(return_value=Attachment)
        self.assertEqual(
            dl_layout._logo_data_uri(env, "/api/attachment/1/download"),
            "https://cdn/logo.png",
        )

    def test_logo_http_fetch(self):
        env = MagicMock()
        env.registry = {}
        mock_resp = MagicMock(status_code=200, content=b"img", headers={"content-type": "image/jpeg"})
        with patch("httpx.get", return_value=mock_resp):
            out = dl_layout._logo_data_uri(env, "https://example.com/logo.jpg")
        self.assertIn("image/jpeg", out)

    def test_google_font_empty(self):
        dl_layout._google_font_embed.cache_clear()
        self.assertEqual(dl_layout._google_font_embed(""), "")

    def test_google_font_embed_success(self):
        dl_layout._google_font_embed.cache_clear()
        css = (
            "@font-face{font-weight:400;src:url(https://x/font.ttf) format('truetype');}"
            "@font-face{font-weight:700;src:url(https://x/bold.ttf) format('truetype');}"
        )
        with patch("httpx.get") as get:
            get.side_effect = [
                MagicMock(text=css),
                MagicMock(content=b"ttf1"),
                MagicMock(content=b"ttf2"),
            ]
            html = dl_layout._google_font_embed("Roboto")
        self.assertIn("<style>", html)
        self.assertIn("Roboto", html)

    def test_google_font_embed_failure_returns_empty(self):
        dl_layout._google_font_embed.cache_clear()
        with patch("httpx.get", side_effect=OSError("offline")):
            self.assertEqual(dl_layout._google_font_embed("Roboto"), "")


class LayoutPreviewExtrasTests(unittest.TestCase):
    def test_render_layout_preview_full_page(self):
        company = SimpleNamespace(id=1)
        Company = MagicMock()
        Company.search.return_value = company
        Company.browse.return_value = company
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=Company)
        with patch.object(dl_layout, "_company_context", return_value=_sample_company_ctx()):
            html = dl_layout.render_layout_preview(env, company_id=1, inline=False)
        self.assertIn("doc-frame", html)

    def test_render_designer_page(self):
        company = SimpleNamespace(
            id=2,
            name="Beta",
            document_layout="light",
            paper_format="A4",
            primary_color="#000",
            secondary_color="#000",
            google_font="",
            logo_url="",
            copyright_text="",
            vat="",
            _address_lines=lambda: ["Line 1"],
        )
        Company = MagicMock()
        Company.search.return_value = company
        Company.browse.return_value = company
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=Company)
        html = dl_layout.render_designer_page(env, company_id=2, csrf_token="tok")
        self.assertIn("Document Layout Designer", html)
        self.assertIn("Beta", html)


class PdfModuleTests(unittest.TestCase):
    @patch("document_layout.pdf.shutil.which", return_value=None)
    def test_html_to_pdf_missing_binary(self, _which):
        with self.assertRaises(RuntimeError) as ctx:
            dl_pdf.html_to_pdf("<html></html>")
        self.assertIn("wkhtmltopdf", str(ctx.exception))

    @patch("document_layout.pdf.subprocess.run")
    @patch("document_layout.pdf.shutil.which", return_value="/usr/bin/wkhtmltopdf")
    def test_html_to_pdf_success(self, _which, run):
        run.return_value = SimpleNamespace(stdout=b"%PDF-1.4", stderr=b"", returncode=0)
        out = dl_pdf.html_to_pdf("<html>x</html>", paper="Letter", landscape=True, footer=False)
        self.assertTrue(out.startswith(b"%PDF"))
        cmd = run.call_args[0][0]
        self.assertIn("Letter", cmd)
        self.assertIn("Landscape", cmd)

    @patch("document_layout.pdf.subprocess.run")
    @patch("document_layout.pdf.shutil.which", return_value="/usr/bin/wkhtmltopdf")
    def test_html_to_pdf_failure(self, _which, run):
        run.return_value = SimpleNamespace(stdout=b"", stderr=b"boom", returncode=1)
        with self.assertRaises(RuntimeError):
            dl_pdf.html_to_pdf("<html></html>")

    @patch("document_layout.pdf.shutil.which", return_value="/usr/bin/wkhtmltopdf")
    def test_is_available(self, _which):
        self.assertTrue(dl_pdf.is_available())


class HooksTests(unittest.TestCase):
    def _conn(self, fetchone_side=None, fetchall_side=None):
        conn = MagicMock()
        if fetchone_side is not None:
            conn.execute.return_value.fetchone.side_effect = fetchone_side
        if fetchall_side is not None:
            conn.execute.return_value.fetchall.return_value = fetchall_side
        return conn

    def test_adopt_legacy_no_report_layout(self):
        env = MagicMock()
        env.conn = self._conn(fetchone_side=[None])
        dl_hooks._adopt_legacy_module(env)
        env.conn.execute.assert_called_once()

    def test_adopt_legacy_rename(self):
        env = MagicMock()
        env.conn = self._conn(fetchone_side=[(1,), None])
        dl_hooks._adopt_legacy_module(env)
        self.assertEqual(env.conn.execute.call_count, 3)

    def test_adopt_legacy_delete_duplicate(self):
        env = MagicMock()
        env.conn = self._conn(fetchone_side=[(1,), (1,)])
        dl_hooks._adopt_legacy_module(env)
        env.conn.execute.assert_any_call(
            'DELETE FROM "ir_module" WHERE "name" = %s', ("report_layout",),
        )

    def test_migrate_both_columns(self):
        env = MagicMock()
        env.conn = self._conn(fetchall_side=[("report_layout",), ("document_layout",)])
        dl_hooks._migrate_company_field(env)
        self.assertGreaterEqual(env.conn.execute.call_count, 2)

    def test_migrate_rename_only(self):
        env = MagicMock()
        env.conn = self._conn(fetchall_side=[("report_layout",)])
        dl_hooks._migrate_company_field(env)
        env.conn.execute.assert_called_with(
            'ALTER TABLE "res_company" RENAME COLUMN "report_layout" TO "document_layout"',
        )

    def test_seed_defaults_skips_without_model(self):
        env = MagicMock()
        env.registry = {}
        dl_hooks._seed_defaults(env)

    def test_seed_defaults_writes_missing_fields(self):
        company = SimpleNamespace(document_layout="", paper_format="")
        company.write = MagicMock()
        Company = MagicMock()
        Company.search.return_value = [company]
        env = MagicMock()
        env.registry = {"res.company": Company}
        env.__getitem__ = MagicMock(return_value=Company)
        dl_hooks._seed_defaults(env)
        company.write.assert_called_once_with(
            {"document_layout": "light", "paper_format": "A4"},
        )

    def test_install_and_sync(self):
        env = MagicMock()
        env.registry = {}
        with patch.object(dl_hooks, "_migrate_company_field") as mig, patch.object(
            dl_hooks, "_seed_defaults",
        ) as seed, patch.object(dl_hooks, "_adopt_legacy_module") as adopt:
            dl_hooks.install(env)
            mig.assert_called_once()
            seed.assert_called_once()
            adopt.assert_not_called()
            dl_hooks.sync(env)
            adopt.assert_called_once()


class WidgetTests(unittest.TestCase):
    def test_design_button_with_record(self):
        rec = SimpleNamespace(id=12)
        html = _render_design_button("", {"_record": rec}, MagicMock())
        self.assertIn("company_id=12", str(html))

    def test_design_button_without_record(self):
        html = _render_design_button("", {}, MagicMock())
        self.assertIn("company_id=0", str(html))


def _mock_company_env(*, uid=1, acl_ok=True):
    company = SimpleNamespace(
        id=5,
        name="Acme",
        document_layout="light",
        paper_format="A4",
        primary_color="#111",
        secondary_color="#222",
        google_font="",
        logo_url="",
        write=MagicMock(),
    )
    Company = MagicMock()
    Company.search.return_value = company
    Company.browse.return_value = company

    env = MagicMock()
    env.uid = uid
    env.conn = MagicMock()
    env.registry = {"res.company": Company, "res.users": MagicMock()}
    if acl_ok:
        env.check_access = MagicMock()
    else:
        env.check_access = MagicMock(side_effect=PermissionError("denied"))

    def getitem(name):
        if name == "res.company":
            return Company
        return MagicMock()

    env.__getitem__ = MagicMock(side_effect=getitem)
    return env, Company, company


@contextmanager
def _web_client(*, uid=1, acl_ok=True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    env, _Company, _company = _mock_company_env(uid=uid, acl_ok=acl_ok)

    @contextmanager
    def connection():
        yield MagicMock()

    pool = MagicMock()
    pool.connection = connection

    app = FastAPI()
    app.state.registry = MagicMock()
    app.state.pool = pool

    def fake_apply(environment, request, **kwargs):
        environment.uid = uid
        return environment

    with patch("document_layout.web.Environment", return_value=env), patch(
        "document_layout.web.apply_request_scope", side_effect=fake_apply,
    ):
        dl_web.register_routes(app)
        request = MagicMock()
        request.state = SimpleNamespace(csrf_token="csrf")
        request.url = SimpleNamespace(path="/web/report/layout/designer", query="")
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, env


class WebRouteTests(unittest.TestCase):
    def setUp(self):
        _reset_registry()
        dl_layout.register_document(
            "demo",
            model="res.partner",
            render_body=lambda e, r: "<b>body</b>",
            title="Demo",
        )

    @patch.object(dl_layout, "render_pdf", return_value=(b"%PDF-x", "A4"))
    def test_print_pdf_authenticated(self, _pdf):
        with _web_client(uid=1) as (client, env):
            Model = MagicMock()
            Model.search.return_value = SimpleNamespace()
            env.__getitem__.side_effect = lambda m: (
                Model if m == "res.partner" else env.__getitem__.return_value
            )
            # Restore company lookup after side_effect override
            company_model = MagicMock()
            def getitem(name):
                if name == "res.partner":
                    return Model
                if name == "res.company":
                    return company_model
                return MagicMock()
            env.__getitem__.side_effect = getitem

            resp = client.get("/report/pdf/demo/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")

    def test_print_pdf_unauthenticated(self):
        with _web_client(uid=None) as (client, _env):
            resp = client.get("/report/pdf/demo/1")
        self.assertEqual(resp.status_code, 401)

    def test_print_pdf_unknown_document(self):
        with _web_client(uid=1) as (client, _env):
            resp = client.get("/report/pdf/unknown/1")
        self.assertEqual(resp.status_code, 404)

    @patch.object(dl_layout, "render_html", return_value="<html>preview</html>")
    def test_preview_html(self, _html):
        with _web_client(uid=1) as (client, env):
            Model = MagicMock()
            Model.search.return_value = SimpleNamespace()

            def getitem(name):
                if name == "res.partner":
                    return Model
                return MagicMock(search=MagicMock(return_value=SimpleNamespace(id=5)))

            env.__getitem__.side_effect = getitem
            resp = client.get("/report/html/demo/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("preview", resp.text)

    @patch.object(dl_layout, "render_layout_preview", return_value="<html>layout</html>")
    def test_preview_layout(self, _prev):
        with _web_client(uid=1) as (client, _env):
            resp = client.get("/report/layout/preview/5")
        self.assertEqual(resp.status_code, 200)

    @patch.object(dl_layout, "render_designer", return_value="<div>designer</div>")
    def test_layout_designer_dialog(self, _des):
        with _web_client(uid=1) as (client, _env):
            resp = client.get("/report/layout/designer?company_id=5")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("designer", resp.text)

    @patch.object(dl_layout, "render_designer_page", return_value="<html>page</html>")
    def test_layout_designer_page(self, _page):
        with _web_client(uid=1) as (client, _env):
            resp = client.get("/web/report/layout/designer?company_id=5")
        self.assertEqual(resp.status_code, 200)

    def test_layout_designer_page_redirects_when_anonymous(self):
        with _web_client(uid=None) as (client, _env):
            resp = client.get("/web/report/layout/designer", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["location"])

    def test_layout_designer_legacy_redirect(self):
        with _web_client(uid=1) as (client, _env):
            resp = client.get("/report/layout/designer/page?company_id=3", follow_redirects=False)
        self.assertEqual(resp.status_code, 301)
        self.assertIn("/web/report/layout/designer", resp.headers["location"])

    @patch.object(dl_layout, "render_layout_preview", return_value="<span>live</span>")
    def test_preview_live_overrides(self, _prev):
        with _web_client(uid=1) as (client, _env):
            resp = client.get(
                "/report/layout/preview-live",
                params={"company_id": 5, "layout": "folder", "color": "#fff"},
            )
        self.assertEqual(resp.status_code, 200)
        _prev.assert_called_once()
        overrides = _prev.call_args.kwargs.get("overrides") or _prev.call_args[1].get("overrides")
        self.assertEqual(overrides["layout"], "folder")

    def test_designer_save(self):
        with _web_client(uid=1) as (client, env):
            company = SimpleNamespace(write=MagicMock())
            Company = MagicMock()
            Company.search.return_value = company
            Company.browse.return_value = company

            def getitem(name):
                if name == "res.company":
                    return Company
                return MagicMock()

            env.__getitem__.side_effect = getitem
            resp = client.post(
                "/report/layout/designer/save",
                json={"company_id": 5, "document_layout": "bold", "paper_format": "A4"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        company.write.assert_called_once()
        env.conn.commit.assert_called_once()

    def test_designer_save_missing_company(self):
        with _web_client(uid=1) as (client, env):
            Company = MagicMock()
            Company.search.return_value = None
            env.__getitem__.side_effect = lambda m: Company if m == "res.company" else MagicMock()
            resp = client.post("/report/layout/designer/save", json={"company_id": 99})
        self.assertEqual(resp.status_code, 404)

    @patch.object(dl_layout, "render_pdf", side_effect=RuntimeError("no wkhtmltopdf"))
    def test_print_pdf_service_unavailable(self, _pdf):
        with _web_client(uid=1) as (client, env):
            Model = MagicMock()
            Model.search.return_value = SimpleNamespace()

            def getitem(name):
                if name == "res.partner":
                    return Model
                return MagicMock()

            env.__getitem__.side_effect = getitem
            resp = client.get("/report/pdf/demo/1")
        self.assertEqual(resp.status_code, 503)

    def test_acl_denied_on_preview_layout(self):
        with _web_client(uid=1, acl_ok=False) as (client, _env):
            resp = client.get("/report/layout/preview/5")
        self.assertEqual(resp.status_code, 403)

    def test_designer_dialog_unauthenticated(self):
        with _web_client(uid=None) as (client, _env):
            resp = client.get("/report/layout/designer")
        self.assertEqual(resp.status_code, 401)

    @patch.object(dl_layout, "render_html", side_effect=ValueError("not found"))
    def test_preview_html_not_found(self, _html):
        with _web_client(uid=1) as (client, env):
            Model = MagicMock()
            Model.search.return_value = SimpleNamespace()
            env.__getitem__.side_effect = lambda m: Model if m == "res.partner" else MagicMock()
            resp = client.get("/report/html/demo/1")
        self.assertEqual(resp.status_code, 404)

    def test_designer_save_unauthenticated(self):
        with _web_client(uid=None) as (client, _env):
            resp = client.post("/report/layout/designer/save", json={"company_id": 5})
        self.assertEqual(resp.status_code, 401)

    def test_designer_save_permission_denied(self):
        with _web_client(uid=1) as (client, env):
            company = SimpleNamespace(write=MagicMock(side_effect=PermissionError("nope")))
            Company = MagicMock()
            Company.search.return_value = company
            Company.browse.return_value = company
            env.__getitem__.side_effect = lambda m: Company if m == "res.company" else MagicMock()
            resp = client.post(
                "/report/layout/designer/save",
                json={"company_id": 5, "document_layout": "bold"},
            )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
