"""Laravel Artisan-style console commands for pyvelm.

Modules register command classes (subclasses of :class:`Command`) via a
``commands/`` package or ``COMMANDS`` in ``__pyvelm__.py``. Users run them as::

    pyvelm make:module inventory
    pyvelm list
    pyvelm help make:module

See :mod:`pyvelm.loader` (:func:`discover_commands`) and ``docs/console.md``.
"""
from __future__ import annotations

import argparse
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

_SIG_RE = re.compile(
    r"\{"
    r"(?P<body>[^}]+)"
    r"\}"
)


@dataclass
class _SigPart:
    """One token from a command signature string."""

    dest: str
    is_option: bool
    optional: bool = False
    flag: bool = False
    default: str | None = None
    help: str | None = None


def parse_signature(signature: str) -> tuple[str, list[_SigPart]]:
    """Parse ``"make:module {name} {--force}"`` into command name + parts."""
    signature = signature.strip()
    if not signature:
        raise ValueError("signature must not be empty")
    first_space = signature.find(" ")
    if first_space == -1:
        return signature, []
    name = signature[:first_space].strip()
    rest = signature[first_space + 1 :]
    parts: list[_SigPart] = []
    for m in _SIG_RE.finditer(rest):
        body = m.group("body").strip()
        optional = body.endswith("?")
        if optional:
            body = body[:-1].strip()
        help_text: str | None = None
        if ":" in body:
            name_part, help_text = body.split(":", 1)
            body = name_part.strip()
            help_text = help_text.strip() or None
        default: str | None = None
        if "=" in body and not body.startswith("--"):
            body, default = body.split("=", 1)
            body = body.strip()
            default = default.strip()
        is_option = body.startswith("--")
        if is_option:
            opt_name = body.lstrip("-")
            value_optional = "=" in opt_name
            if value_optional:
                optional = True
                opt_name, opt_default = opt_name.split("=", 1)
                if default is None:
                    default = opt_default.strip() or None
            dest = opt_name.replace("-", "_")
            flag = not value_optional and default is None
            parts.append(
                _SigPart(
                    dest=dest,
                    is_option=True,
                    optional=optional,
                    flag=flag,
                    default=default,
                    help=help_text,
                )
            )
        else:
            parts.append(
                _SigPart(
                    dest=body,
                    is_option=False,
                    optional=optional,
                    default=default,
                    help=help_text,
                )
            )
    return name, parts


def _build_argparse(command: Command) -> argparse.ArgumentParser:
    cmd_name, parts = parse_signature(command.signature or command.name)
    parser = argparse.ArgumentParser(
        prog=f"pyvelm {cmd_name}",
        description=command.description or None,
    )
    for part in parts:
        if part.is_option:
            if part.flag:
                parser.add_argument(
                    f"--{part.dest.replace('_', '-')}",
                    dest=part.dest,
                    action="store_true",
                    default=False,
                    help=part.help,
                )
            else:
                kwargs = {
                    "dest": part.dest,
                    "help": part.help,
                    "required": not part.optional,
                }
                if part.optional:
                    kwargs["nargs"] = "?"
                    kwargs["default"] = part.default
                elif part.default is not None:
                    kwargs["default"] = part.default
                parser.add_argument(
                    f"--{part.dest.replace('_', '-')}",
                    **kwargs,
                )
        else:
            kwargs: dict[str, Any] = {"help": part.help}
            if part.optional:
                kwargs["nargs"] = "?"
                kwargs["default"] = part.default
            parser.add_argument(part.dest, **kwargs)
    return parser


@dataclass
class CommandContext:
    """Runtime context passed to :meth:`Command.handle`."""

    roots: list[Path] = field(default_factory=list)
    env: Any = None  # Environment | None — avoid import cycle
    registry: Any = None

    def info(self, message: str) -> None:
        print(message)

    def line(self, message: str = "") -> None:
        print(message)

    def warn(self, message: str) -> None:
        print(f"warning: {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        print(f"error: {message}", file=sys.stderr)


class Command(ABC):
    """Base class for Artisan-style commands.

    Subclass and set ``name``, ``description``, ``signature``, then
    implement :meth:`handle`. Return an int exit code (0 = success).

    Example::

        class HelloCommand(Command):
            name = "demo:hello"
            description = "Say hello"
            signature = "demo:hello {name}"

            def handle(self, name: str) -> int:
                self.info(f"Hello, {name}!")
                return 0
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    signature: ClassVar[str] = ""
    requires_db: ClassVar[bool] = False

    _ctx: CommandContext | None = None

    @property
    def info(self):
        return self._ctx.info  # type: ignore[union-attr]

    @property
    def line(self):
        return self._ctx.line  # type: ignore[union-attr]

    @property
    def warn(self):
        return self._ctx.warn  # type: ignore[union-attr]

    @property
    def error(self):
        return self._ctx.error  # type: ignore[union-attr]

    def run(self, ctx: CommandContext, argv: list[str]) -> int:
        """Parse ``argv`` against :attr:`signature` and call :meth:`handle`."""
        self._ctx = ctx
        if not self.signature and not self.name:
            raise ValueError(f"{type(self).__name__} needs name= or signature=")
        parser = _build_argparse(self)
        args = parser.parse_args(argv)
        return self.handle(**vars(args))

    @abstractmethod
    def handle(self, **kwargs: Any) -> int:
        """Command body — keyword args match the signature tokens."""
        ...


class CommandRegistry:
    """Registered commands keyed by ``name`` (e.g. ``make:module``)."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        name = command.name or parse_signature(command.signature)[0]
        if not name:
            raise ValueError(f"{type(command).__name__} has no command name")
        command.name = name
        if name in self._commands:
            existing = self._commands[name]
            raise ValueError(
                f"Duplicate command {name!r}: "
                f"{type(existing).__name__} and {type(command).__name__}"
            )
        self._commands[name] = command

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def all(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    def names(self) -> list[str]:
        return sorted(self._commands)

    def run(
        self,
        name: str,
        argv: list[str],
        *,
        ctx: CommandContext,
    ) -> int:
        cmd = self.get(name)
        if cmd is None:
            raise KeyError(name)
        if cmd.requires_db and ctx.env is None:
            from .cli import bootstrap_command_env

            bootstrap_command_env(ctx)
        return cmd.run(ctx, argv)

    def print_list(self) -> None:
        if not self._commands:
            print("No module commands registered.")
            return
        width = max(len(c.name) for c in self.all())
        for cmd in self.all():
            desc = (cmd.description or "").strip()
            pad = " " * (width - len(cmd.name) + 2)
            print(f"  {cmd.name}{pad}{desc}")
