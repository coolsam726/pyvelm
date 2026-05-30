"""Unit tests for ``pyvelm.server``."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from pyvelm.runtime import DEVELOPMENT, PRODUCTION
from pyvelm.server import (
    apply_runtime_env,
    default_serve_env,
    guess_serve_import,
    prepare_reload_import,
    run_dev_server,
)


class ApplyRuntimeEnvTests(unittest.TestCase):
    def test_none_returns_current_env(self):
        with patch.dict(os.environ, {"PYVELM_ENV": "production"}, clear=False):
            self.assertEqual(apply_runtime_env(None), "production")

    def test_explicit_sets_environ(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_ENV", None)
            env = apply_runtime_env("development")
            self.assertEqual(env, "development")
            self.assertEqual(os.environ["PYVELM_ENV"], "development")


class DefaultServeEnvTests(unittest.TestCase):
    def test_cli_defaults_development(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_ENV", None)
            self.assertEqual(default_serve_env(from_cli=True), DEVELOPMENT)

    def test_non_cli_defaults_production(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_ENV", None)
            self.assertEqual(default_serve_env(from_cli=False), PRODUCTION)

    def test_respects_existing_pyvelm_env(self):
        with patch.dict(os.environ, {"PYVELM_ENV": "production"}, clear=False):
            self.assertEqual(default_serve_env(from_cli=True), "production")


class RunDevServerTests(unittest.TestCase):
    @patch("uvicorn.run")
    def test_serves_app_in_development(self, run):
        app = MagicMock()
        with patch("builtins.print"):
            run_dev_server(app=app, host="0.0.0.0", port=9000, runtime_env="development")
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertIs(args[0], app)
        self.assertEqual(kwargs["host"], "0.0.0.0")
        self.assertEqual(kwargs["port"], 9000)
        self.assertEqual(kwargs["log_level"], "debug")

    @patch("uvicorn.run")
    def test_serves_app_in_production_log_level(self, run):
        app = MagicMock()
        with patch("builtins.print"):
            run_dev_server(app=app, runtime_env="production")
        self.assertEqual(run.call_args[1]["log_level"], "info")

    @patch("uvicorn.run")
    def test_reload_with_import_string(self, run):
        with patch("builtins.print"):
            run_dev_server(
                app="myapp.main:app",
                reload=True,
                reload_dirs=["/tmp/pkg"],
                runtime_env="development",
            )
        run.assert_called_once_with(
            "myapp.main:app",
            host="127.0.0.1",
            port=8000,
            log_level="debug",
            reload=True,
            reload_dirs=["/tmp/pkg"],
        )

    @patch("uvicorn.run")
    def test_reload_ignored_in_production(self, run):
        app = MagicMock()
        with patch("builtins.print"):
            run_dev_server(app=app, reload=True, runtime_env="production")
        self.assertNotIn("reload", run.call_args[1])
        self.assertIs(run.call_args[0][0], app)

    def test_reload_requires_import_string(self):
        with patch("uvicorn.run"), patch("builtins.print"):
            with self.assertRaises(ValueError):
                run_dev_server(app=MagicMock(), reload=True, runtime_env="development")

    @patch("uvicorn.run")
    def test_development_prints_docs_hint(self, run):
        app = MagicMock()
        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            run_dev_server(app=app, port=8080, runtime_env="development")
        text = "\n".join(printed)
        self.assertIn("/docs", text)
        self.assertIn("admin / admin", text)
        run.assert_called_once()


class ServeImportTests(unittest.TestCase):
    def test_guess_app_serve(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "serve.py").write_text("# stub\n", encoding="utf-8")
            self.assertEqual(guess_serve_import(project_root=root), "app.serve:app")

    def test_guess_examples_serve(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "examples").mkdir()
            (root / "examples" / "serve.py").write_text("# stub\n", encoding="utf-8")
            self.assertEqual(
                guess_serve_import(project_root=root), "examples.serve:app",
            )

    def test_prepare_reload_import_app(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            with patch("pyvelm.scaffolder.find_project_root", return_value=root):
                dirs = prepare_reload_import("app.serve:app")
            self.assertIn(str(root), dirs)
            self.assertIn(str(root / "app"), dirs)
            self.assertIn(str(root), sys.path)


if __name__ == "__main__":
    unittest.main()
