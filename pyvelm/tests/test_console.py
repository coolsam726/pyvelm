"""Tests for ``pyvelm.console`` (Artisan-style commands)."""
from __future__ import annotations

import io
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm.console import (
    Command,
    CommandContext,
    CommandRegistry,
    _build_argparse,
    parse_signature,
)


class ParseSignatureTests(unittest.TestCase):
    def test_name_only(self):
        self.assertEqual(parse_signature("demo:hello"), ("demo:hello", []))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_signature("   ")

    def test_optional_arg_and_help(self):
        name, parts = parse_signature("cmd {name?}")
        self.assertEqual(name, "cmd")
        self.assertTrue(parts[0].optional)
        _, parts2 = parse_signature("cmd {name : optional name}")
        self.assertEqual(parts2[0].help, "optional name")

    def test_option_with_default_and_value(self):
        name, parts = parse_signature("cmd {--tag=beta}")
        self.assertEqual(parts[0].dest, "tag")
        self.assertEqual(parts[0].default, "beta")

    def test_flag_option(self):
        _, parts = parse_signature("cmd {--force}")
        self.assertTrue(parts[0].flag)
        self.assertTrue(parts[0].is_option)


class CommandContextTests(unittest.TestCase):
    def test_output_helpers(self):
        ctx = CommandContext()
        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stderr", io.StringIO()):
            ctx.info("hello")
            ctx.line()
            ctx.warn("careful")
            ctx.error("bad")
        out = buf.getvalue()
        self.assertIn("hello", out)


class _DemoCommand(Command):
    name = "demo:run"
    description = "Demo"
    signature = "demo:run {name} {--force} {--tag=default}"

    def handle(self, name: str, force: bool = False, tag: str = "default") -> int:
        self.info(f"{name}:{tag}:{'force' if force else 'no'}")
        return 0


class _DbCommand(Command):
    name = "demo:db"
    requires_db = True
    signature = "demo:db"

    def handle(self) -> int:
        self.info("db-ok" if self._ctx.env else "no-env")
        return 0


class CommandRunTests(unittest.TestCase):
    def test_run_parses_and_calls_handle(self):
        cmd = _DemoCommand()
        ctx = CommandContext()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cmd.run(ctx, ["alice", "--force", "--tag", "x"])
        self.assertEqual(code, 0)
        self.assertIn("alice:x:force", buf.getvalue())

    def test_build_argparse_help(self):
        parser = _build_argparse(_DemoCommand())
        self.assertIn("demo:run", parser.format_help())


class CommandRegistryTests(unittest.TestCase):
    def test_register_duplicate_raises(self):
        reg = CommandRegistry()
        reg.register(_DemoCommand())
        with self.assertRaises(ValueError):
            reg.register(_DemoCommand())

    def test_register_from_signature_only(self):
        class SigOnly(Command):
            signature = "only:sig"
            description = "x"

            def handle(self, **kwargs) -> int:
                return 0

        reg = CommandRegistry()
        reg.register(SigOnly())
        self.assertEqual(reg.get("only:sig").name, "only:sig")

    def test_print_list_empty(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            CommandRegistry().print_list()
        self.assertIn("No module commands", buf.getvalue())

    def test_print_list_formats_commands(self):
        reg = CommandRegistry()
        reg.register(_DemoCommand())
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            reg.print_list()
        self.assertIn("demo:run", buf.getvalue())

    def test_run_requires_db_bootstraps(self):
        reg = CommandRegistry()
        reg.register(_DbCommand())
        ctx = CommandContext(roots=[])
        with patch("pyvelm.cli.bootstrap_command_env") as boot:
            boot.side_effect = lambda c: setattr(c, "env", object())
            code = reg.run("demo:db", [], ctx=ctx)
        self.assertEqual(code, 0)
        boot.assert_called_once()

    def test_run_missing_command_raises(self):
        with self.assertRaises(KeyError):
            CommandRegistry().run("nope", [], ctx=CommandContext())

    def test_run_propagates_handler_exception(self):
        class Boom(Command):
            name = "boom"
            signature = "boom"

            def handle(self, **kwargs) -> int:
                raise ValueError("kaboom")

        reg = CommandRegistry()
        reg.register(Boom())
        with self.assertRaises(ValueError):
            reg.run("boom", [], ctx=CommandContext())


class CommandValidationTests(unittest.TestCase):
    def test_run_without_name_or_signature_raises(self):
        class Empty(Command):
            def handle(self, **kwargs) -> int:
                return 0

        with self.assertRaises(ValueError):
            Empty().run(CommandContext(), [])

    def test_optional_positional_omitted(self):
        class OptCmd(Command):
            signature = "opt:cmd {name?}"

            def handle(self, name: str | None = None, **kwargs) -> int:
                return 0 if name is None else 1

        self.assertEqual(OptCmd().run(CommandContext(), []), 0)
        self.assertEqual(OptCmd().run(CommandContext(), ["alice"]), 1)

    def test_option_with_default_not_optional(self):
        class OptCmd(Command):
            signature = "opt:flag {--size=5}"

            def handle(self, size: str = "5", **kwargs) -> int:
                return 0

        parser = _build_argparse(OptCmd())
        self.assertIn("--size", parser.format_help())


if __name__ == "__main__":
    unittest.main()
